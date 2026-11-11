import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio. Tests opt in with @pytest.mark.anyio."""
    return "asyncio"
