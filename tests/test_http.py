"""The HTTP layer against a scripted transport and a clock that only moves when told. No network."""

import json

import httpx2
import pytest

from hepph_paper_miner.http import CACHE_ENV, Fetcher, FetchError, default_cache_dir

URL = "https://example.org/thing"


class Script:
    """Answers requests from a list, in order, and records when each request arrived."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []
        self.times: list[float] = []
        self.now = 0.0

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        self.times.append(self.now)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx2.Response(status, content=body, headers={"content-type": "text/plain"})

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def fetcher(self, cache_dir, **options) -> Fetcher:
        return Fetcher(
            cache_dir,
            transport=httpx2.MockTransport(self.handler),
            sleep=self.sleep,
            clock=self.clock,
            **options,
        )


def test_second_get_of_the_same_request_comes_from_the_cache(tmp_path):
    script = Script((200, b"hello"))
    fetcher = script.fetcher(tmp_path)

    first = fetcher.get(URL, {"b": "2", "a": "1"})
    second = fetcher.get(URL, {"a": "1", "b": "2"})  # same request, parameters in another order

    assert (first.body, first.from_cache) == (b"hello", False)
    assert (second.body, second.from_cache) == (b"hello", True)
    assert second.fetched_at == first.fetched_at
    assert len(script.requests) == 1
    assert script.requests[0].headers["user-agent"] == "hepph-paper-miner"


def test_cache_record_describes_the_body_and_no_temporary_file_is_left(tmp_path):
    script = Script((200, b"hello"))
    script.fetcher(tmp_path).get(URL, {"a": "1"})

    (record,) = tmp_path.glob("*/*.json")
    (body,) = tmp_path.glob("*/*.body")
    meta = json.loads(record.read_text(encoding="utf-8"))
    assert meta["url"] == URL and meta["params"] == {"a": "1"} and meta["bytes"] == 5
    assert body.read_bytes() == b"hello"
    assert not list(tmp_path.glob("*/*.tmp"))


def test_requests_are_kept_three_seconds_apart(tmp_path):
    script = Script((200, b"1"), (200, b"2"), (200, b"3"))
    fetcher = script.fetcher(tmp_path)

    fetcher.get(URL, {"n": "1"})
    script.now += 1.0  # one second passes by itself
    fetcher.get(URL, {"n": "2"})
    script.now += 10.0  # long enough: no extra wait
    fetcher.get(URL, {"n": "3"})

    assert script.times == [0.0, 3.0, 13.0]


def test_a_cache_hit_does_not_wait(tmp_path):
    script = Script((200, b"1"))
    fetcher = script.fetcher(tmp_path)
    fetcher.get(URL)
    fetcher.get(URL)
    assert script.now == 0.0


def test_busy_answers_are_retried_with_longer_waits(tmp_path):
    script = Script((429, b""), (503, b""), (200, b"at last"))
    fetched = script.fetcher(tmp_path).get(URL)

    assert fetched.body == b"at last"
    assert script.times == [0.0, 6.0, 18.0]  # waits of 6 and 12 seconds


def test_still_busy_after_three_retries_is_reported_as_busy(tmp_path):
    script = Script(*[(503, b"")] * 4)
    with pytest.raises(FetchError) as caught:
        script.fetcher(tmp_path).get(URL)

    assert (caught.value.reason, caught.value.status) == ("busy", 503)
    assert len(script.requests) == 4
    assert not list(tmp_path.glob("*/*"))  # failures are not cached


@pytest.mark.parametrize(
    ("status", "reason"), [(404, "not_found"), (400, "rejected"), (403, "rejected")]
)
def test_client_errors_fail_at_once(tmp_path, status, reason):
    script = Script((status, b""))
    with pytest.raises(FetchError) as caught:
        script.fetcher(tmp_path).get(URL)

    assert (caught.value.reason, caught.value.status) == (reason, status)
    assert len(script.requests) == 1


def test_one_timeout_is_retried_and_a_second_one_is_reported(tmp_path):
    script = Script(httpx2.ReadTimeout("slow"), (200, b"ok"))
    assert script.fetcher(tmp_path).get(URL).body == b"ok"
    assert script.times == [0.0, 3.0]

    script = Script(httpx2.ReadTimeout("slow"), httpx2.ConnectTimeout("slow"))
    with pytest.raises(FetchError) as caught:
        script.fetcher(tmp_path).get(URL, {"other": "1"})
    assert caught.value.reason == "timeout"


def test_a_broken_connection_counts_as_busy(tmp_path):
    script = Script(httpx2.ConnectError("refused"), (200, b"ok"))
    assert script.fetcher(tmp_path).get(URL).body == b"ok"

    script = Script(*[httpx2.ConnectError("refused")] * 2)
    with pytest.raises(FetchError) as caught:
        script.fetcher(tmp_path, busy_retries=1).get(URL, {"other": "1"})
    assert caught.value.reason == "busy"


def test_a_damaged_cache_entry_is_fetched_again(tmp_path):
    script = Script((200, b"good"), (200, b"good"))
    fetcher = script.fetcher(tmp_path)
    fetcher.get(URL)
    (body,) = tmp_path.glob("*/*.body")
    body.write_bytes(b"damaged")

    again = fetcher.get(URL)

    assert (again.body, again.from_cache) == (b"good", False)
    assert body.read_bytes() == b"good"


def test_refresh_fetches_again_and_replaces_the_entry(tmp_path):
    script = Script((200, b"old"), (200, b"new"))
    fetcher = script.fetcher(tmp_path)
    fetcher.get(URL)

    assert fetcher.get(URL, refresh=True).body == b"new"
    assert fetcher.get(URL).body == b"new"
    assert len(script.requests) == 2


def test_a_forgotten_answer_is_asked_for_again(tmp_path):
    script = Script((200, b"bad"), (200, b"good"), (200, b"other"))
    fetcher = script.fetcher(tmp_path)
    fetcher.get(URL, {"a": "1"})
    fetcher.get(URL, {"a": "2"})

    fetcher.forget(URL, {"a": "1"})
    fetcher.forget(URL, {"a": "1"})  # nothing left to remove: not an error

    assert fetcher.get(URL, {"a": "2"}).from_cache is True  # other answers are untouched
    again = fetcher.get(URL, {"a": "1"})
    assert (again.body, again.from_cache) == (b"other", False)
    script.fetcher(None).forget(URL)  # no cache folder: nothing to do


def test_without_a_cache_folder_every_get_is_a_request():
    script = Script((200, b"1"), (200, b"1"))
    fetcher = script.fetcher(None)
    fetcher.get(URL)
    fetcher.get(URL)
    assert len(script.requests) == 2


def test_fetch_error_survives_pickle():
    import pickle

    clone = pickle.loads(pickle.dumps(FetchError("busy", URL, 503)))
    assert (clone.reason, clone.url, clone.status) == ("busy", URL, 503)


def test_cache_folder_is_under_home_unless_the_environment_names_one(monkeypatch, tmp_path):
    monkeypatch.delenv(CACHE_ENV, raising=False)
    assert default_cache_dir().parts[-2:] == (".cache", "hepph-paper-miner")
    assert "AppData" not in default_cache_dir().parts[-3:]

    monkeypatch.setenv(CACHE_ENV, str(tmp_path))
    assert default_cache_dir() == tmp_path
