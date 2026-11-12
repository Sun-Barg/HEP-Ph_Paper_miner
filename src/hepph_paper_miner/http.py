"""The one place that talks to the network.

It does four things for every GET: keep requests apart in time, give up after a
time limit, sort failures into a few reasons, and keep successful answers on disk.
It knows nothing about arXiv or papers; the sources decide what a failure means.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx2

logger = logging.getLogger(__name__)

CACHE_ENV = "HEPPH_PAPER_MINER_CACHE"


def default_cache_dir() -> Path:
    """Where answers are kept unless the environment says otherwise.

    Under the home directory, not the current directory (a host starts the server
    wherever it likes) and not under AppData (Windows may redirect what a packaged
    app writes there). Outside the repository, so paper text cannot be committed.
    """
    configured = os.environ.get(CACHE_ENV)
    return Path(configured) if configured else Path.home() / ".cache" / "hepph-paper-miner"


class FetchError(Exception):
    """A request that did not produce an answer.

    reason: "not_found" (404), "rejected" (another 4xx), "busy" (429, 5xx or a broken
    connection, also after retries), "timeout".
    """

    def __init__(self, reason: str, url: str, status: int | None = None) -> None:
        super().__init__(reason, url, status)  # all arguments, so that it survives pickle
        self.reason = reason
        self.url = url
        self.status = status

    def __str__(self) -> str:
        return f"{self.reason}: {self.url} (status {self.status})"


@dataclass(frozen=True)
class Fetched:
    body: bytes
    from_cache: bool
    fetched_at: str  # UTC, ISO 8601: when the body came from the network


class Fetcher:
    """GET with pacing, a time limit, retries and a disk cache.

    One instance holds one lock and one connection, so requests made through it
    never overlap. That holds inside one process only.
    """

    def __init__(
        self,
        cache_dir: Path | None,
        *,
        min_interval: float = 3.0,
        timeout: float = 30.0,
        busy_retries: int = 3,
        timeout_retries: int = 1,
        user_agent: str = "hepph-paper-miner",
        transport: httpx2.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cache_dir = cache_dir
        self._min_interval = min_interval
        self._busy_retries = busy_retries
        self._timeout_retries = timeout_retries
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last_request_end: float | None = None
        self._client = httpx2.Client(
            transport=transport,
            timeout=httpx2.Timeout(timeout),
            limits=httpx2.Limits(max_connections=1),
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )

    def get(
        self, url: str, params: Mapping[str, str] | None = None, *, refresh: bool = False
    ) -> Fetched:
        """Return the body for a 200 answer, from the cache when it is there.

        Only 200 answers are cached, and they never expire: pass refresh=True to
        fetch again, or call forget() when an answer turns out to be unusable.
        Raises FetchError for everything else.
        """
        params = dict(params or {})
        with self._lock:
            if not refresh:
                cached = self._read_cache(url, params)
                if cached is not None:
                    return cached
            body, content_type = self._request(url, params)
            fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
            self._write_cache(url, params, body, content_type, fetched_at)
            return Fetched(body, from_cache=False, fetched_at=fetched_at)

    def forget(self, url: str, params: Mapping[str, str] | None = None) -> None:
        """Remove the kept answer for a request, so that the next get() asks again.

        A 200 answer is kept before anyone has read it. The caller that finds it
        unusable (an empty listing, a page that is not the paper) calls this;
        otherwise one bad answer would be served from the cache from then on.
        """
        paths = self._paths(url, dict(params or {}))
        if paths is None:
            return
        with self._lock:
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    logger.warning("could not remove a cache entry (%s): %s", error, path)

    # --- network -----------------------------------------------------------------

    def _request(self, url: str, params: dict[str, str]) -> tuple[bytes, str]:
        busy_left, timeout_left = self._busy_retries, self._timeout_retries
        wait = self._min_interval
        while True:
            self._wait_for_turn(wait)
            try:
                response = self._client.get(url, params=params)
            except httpx2.TimeoutException as error:
                self._last_request_end = self._clock()
                if timeout_left == 0:
                    raise FetchError("timeout", url) from error
                timeout_left -= 1
                logger.warning("timeout, trying again: %s", url)
                continue
            except httpx2.TransportError as error:
                self._last_request_end = self._clock()
                if busy_left == 0:
                    raise FetchError("busy", url) from error
                busy_left -= 1
                wait *= 2
                logger.warning(
                    "connection failed (%s), waiting %.0f s: %s", type(error).__name__, wait, url
                )
                continue
            self._last_request_end = self._clock()

            status = response.status_code
            if status == 200:
                return response.content, response.headers.get("content-type", "")
            if status == 404:
                raise FetchError("not_found", url, status)
            if status == 429 or status >= 500:
                if busy_left == 0:
                    raise FetchError("busy", url, status)
                busy_left -= 1
                wait *= 2
                logger.warning("status %d, waiting %.0f s: %s", status, wait, url)
                continue
            raise FetchError("rejected", url, status)

    def _wait_for_turn(self, interval: float) -> None:
        """Sleep until `interval` seconds have passed since the last request ended."""
        if self._last_request_end is None:
            return
        remaining = interval - (self._clock() - self._last_request_end)
        if remaining > 0:
            self._sleep(remaining)

    # --- cache -------------------------------------------------------------------

    def _paths(self, url: str, params: dict[str, str]) -> tuple[Path, Path] | None:
        if self._cache_dir is None:
            return None
        # The key is the request itself, with the parameters in a fixed order.
        canonical = "GET " + url + "?" + urlencode(sorted(params.items()))
        key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        folder = self._cache_dir / key[:2]
        return folder / f"{key}.body", folder / f"{key}.json"

    def _read_cache(self, url: str, params: dict[str, str]) -> Fetched | None:
        paths = self._paths(url, params)
        if paths is None:
            return None
        body_path, meta_path = paths
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
        except (OSError, ValueError):
            return None
        # A body that does not match its record (a crash between the two writes, a
        # damaged file) is not trusted: fetch again.
        if hashlib.sha256(body).hexdigest() != meta.get("sha256"):
            logger.warning("cache entry does not match its record, fetching again: %s", url)
            return None
        return Fetched(body, from_cache=True, fetched_at=meta.get("fetched_at", ""))

    def _write_cache(
        self, url: str, params: dict[str, str], body: bytes, content_type: str, fetched_at: str
    ) -> None:
        paths = self._paths(url, params)
        if paths is None:
            return
        body_path, meta_path = paths
        meta = {
            "url": url,
            "params": params,
            "fetched_at": fetched_at,
            "content_type": content_type,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        try:
            body_path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(body_path, body)
            _write_atomic(meta_path, json.dumps(meta, indent=2).encode("utf-8"))
        except OSError as error:
            # The cache saves time and requests; it is not needed for a correct answer.
            logger.warning("could not write the cache (%s): %s", error, body_path.parent)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write to a temporary file beside the target, then rename: readers see all or nothing."""
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
