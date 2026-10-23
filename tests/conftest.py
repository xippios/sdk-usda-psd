import pytest

from xippios.usda.psd import _client
from xippios.usda.psd._client import API_KEY_ENV, RELEASE_DATES_CACHE, auth

pytest_plugins = ["xippios.core.testing.plugin"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


PLACEHOLDER_KEY = "placeholder-for-fixture-replay"


@pytest.fixture(autouse=True)
def placeholder_api_key(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> str | None:
    """Every test but a live one sends the placeholder key, whatever the shell holds.

    Setting the variable is not enough: the client's auth resolves the key once per auth
    object and caches it, so a live test earlier in the same run would leave the real
    key in place. ``auth.key``, through which every ``xippios.core`` auth class reads the
    key, is pinned to the placeholder as well; both come back after the test. Returns
    the placeholder, or ``None`` in a live test, which uses the key in the environment.
    """
    if "live" in request.keywords:
        return None
    monkeypatch.setenv(API_KEY_ENV, PLACEHOLDER_KEY)
    monkeypatch.setattr(auth, "key", lambda: PLACEHOLDER_KEY)
    return PLACEHOLDER_KEY


@pytest.fixture(autouse=True)
def fresh_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts without a quota snapshot, so no replayed answer makes the next pause."""
    monkeypatch.setattr(_client, "_quota", None)


@pytest.fixture(autouse=True)
def fresh_release_dates(request: pytest.FixtureRequest) -> None:
    """Replay tests start with an empty release-date cache, so every route is really called.

    Live tests share it: the release dates one live test fetched serve the next, which
    keeps the live run within its call budget.
    """
    if "live" not in request.keywords:
        RELEASE_DATES_CACHE.clear()
