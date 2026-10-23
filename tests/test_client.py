"""The client's error mapping and api.data.gov quota handling.

Recorded answers come from ``tests/fixtures``, the gateway's 429 included
(``PSDData_GetCommodities/over_rate_limit.json``, recorded after spending the key's
hourly quota on 2026-10-23). Cases the recordings do not cover (the gateway's
``NOT_FOUND`` 404, the other ``API_KEY_*`` codes, a 429 without ``Retry-After`` or with
a short one) are built in the recorded body's shape and say so.
"""

import dataclasses
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from xippios.core import (
    AuthError,
    MemoryCache,
    NotFoundError,
    RateLimitError,
    RetryPolicy,
    UpstreamError,
)
from xippios.core.mcp.errors import error_to_text
from xippios.core.testing import load_fixture

from xippios.usda.psd import api
from xippios.usda.psd._client import (
    API_KEY_ENV,
    BASE_URL,
    QUOTA_WINDOW,
    RATE_LIMIT,
    QuotaAwareClient,
    auth,
    classify,
    client,
    config,
    observe_quota,
    quota,
    quota_pause,
)
from xippios.usda.psd.errors import NoDataForYear

FIXTURES = Path(__file__).parent / "fixtures"
DATA = "PSDData_GetCountryCommodityDataByYear"
NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


def recorded(endpoint: str, case: str) -> httpx.Response:
    """A recorded answer as an ``httpx.Response``, for calling ``classify`` directly."""
    fixture = load_fixture(FIXTURES / endpoint / f"{case}.json")
    return httpx.Response(
        fixture.response.status,
        headers=fixture.response.headers,
        content=fixture.response.content,
        request=httpx.Request(fixture.request.method, fixture.request.url),
    )


def synthesised(status: int, body: object, headers: dict[str, str] | None = None) -> httpx.Response:
    """NOT RECORDED as such: an answer in the shape api.data.gov documents and sends."""
    return httpx.Response(
        status,
        json=body,
        headers=headers or {},
        request=httpx.Request("GET", f"{BASE_URL}/api/psd/commodities"),
    )


OVER_RATE_LIMIT = json.loads(
    load_fixture(FIXTURES / "PSDData_GetCommodities" / "over_rate_limit.json").response.body
)
"""The recorded 429 body, for the variants built around it."""


def test_rate_limit_is_one_request_per_second_without_burst() -> None:
    assert (RATE_LIMIT.per_minute, RATE_LIMIT.capacity) == (60, 1)
    assert config.rate_limit is RATE_LIMIT
    assert config.classify is classify
    assert isinstance(client, QuotaAwareClient)
    assert auth.header == "X-Api-Key"
    assert auth.env_var == API_KEY_ENV == "DATA_GOV_API_KEY"  # pragma: allowlist secret


def test_invalid_key_is_an_auth_error_naming_the_code_and_the_variable() -> None:
    response = recorded("PSDData_GetCommodities", "invalid_key")
    error = classify(response)
    assert isinstance(error, AuthError)
    assert error.status == 403
    assert "API_KEY_INVALID" in error.message
    assert API_KEY_ENV in error.message
    assert "An invalid api_key was supplied" in error.message
    assert error.source == "usda-psd"


@pytest.mark.parametrize(
    "code",
    ["API_KEY_MISSING", "API_KEY_DISABLED", "API_KEY_UNAUTHORIZED", "API_KEY_UNVERIFIED"],
)
def test_every_documented_key_code_is_an_auth_error(code: str) -> None:
    """NOT RECORDED: the other documented codes, in the recorded body's shape."""
    error = classify(synthesised(403, {"error": {"code": code, "message": "documented"}}))
    assert isinstance(error, AuthError)
    assert code in error.message


def test_a_403_without_a_gateway_code_falls_through_to_core() -> None:
    assert classify(synthesised(403, {"Message": "Access denied"})) is None


@pytest.mark.anyio
async def test_the_wrapper_raises_auth_error_on_the_recorded_invalid_key(
    replay_fixture: Callable[[str, str], respx.Route],
    placeholder_api_key: str,
) -> None:
    route = replay_fixture("PSDData_GetCommodities", "invalid_key")
    with pytest.raises(AuthError, match="API_KEY_INVALID") as info:
        await api.PSDData_GetCommodities()
    assert placeholder_api_key not in str(info.value)
    assert route.call_count == 1, "a 403 is never retried"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case", "path"),
    [
        ("unknown_commodity", "/api/psd/commodity/9999999/country/US/year/2023"),
        ("unknown_country", "/api/psd/commodity/0410000/country/XX/year/2023"),
    ],
)
async def test_unknown_codes_answer_an_empty_list_not_an_error(
    replay_fixture: Callable[[str, str], respx.Route], case: str, path: str
) -> None:
    replay_fixture(DATA, case)
    assert classify(recorded(DATA, case)) is None
    assert await client.get_json(path) == []


@pytest.mark.anyio
async def test_a_year_without_data_answers_404_with_an_empty_body(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    response = recorded(DATA, "unknown_year")
    assert (response.status_code, response.content) == (404, b"")
    error = classify(response)
    assert isinstance(error, NotFoundError)
    assert "no data for /api/psd/commodity/0410000/country/US/year/1900" in error.message
    route = replay_fixture(DATA, "unknown_year")
    with pytest.raises(NotFoundError, match="empty body"):
        await client.get_json("/api/psd/commodity/0410000/country/US/year/1900")
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("endpoint", "case"),
    [
        ("PSDData_GetCountryCommodityDataByYear", "unknown_year"),
        ("PSDData_GetCommodityDataByYear", "year_1900"),
        ("PSDData_GetWorldCommodityDataByYear", "year_1900"),
    ],
)
def test_every_data_form_answers_a_year_without_data_with_an_empty_404(
    endpoint: str, case: str
) -> None:
    response = recorded(endpoint, case)
    assert (response.status_code, response.content) == (404, b"")
    assert response.headers["content-type"].startswith("text/plain")
    error = classify(response)
    assert isinstance(error, NoDataForYear)
    assert isinstance(error, NotFoundError), "in the taxonomy, conventions §5"
    assert error.path == response.request.url.path
    assert f"no data for {error.path} (HTTP 404 with an empty body)" in error.message


def test_the_content_type_is_compared_without_case() -> None:
    """NOT RECORDED as such: the recorded empty 404 with its content type upper-cased.
    Media types are case-insensitive (RFC 9110), so it is still PSD's empty year."""
    fixture = load_fixture(FIXTURES / DATA / "unknown_year.json")
    response = httpx.Response(
        404,
        headers=[("Content-Type", "TEXT/PLAIN; charset=utf-8")],
        content=b"",
        request=httpx.Request("GET", fixture.request.url),
    )
    assert isinstance(classify(response), NoDataForYear)


def test_an_empty_404_is_no_data_for_year_only_on_a_data_path_as_text() -> None:
    """NOT RECORDED: the recorded empty 404 moved off a data path, or without its
    ``text/plain``. Neither is PSD's answer for an empty year, so neither is skipped by a
    series: both stay a plain ``NotFoundError``."""
    fixture = load_fixture(FIXTURES / DATA / "unknown_year.json")
    for url, headers in [
        (f"{BASE_URL}/api/psd/commodity/0410000/dataReleaseDates", fixture.response.headers),
        (fixture.request.url, [("content-type", "application/json")]),
    ]:
        response = httpx.Response(
            404, headers=headers, content=b"", request=httpx.Request("GET", url)
        )
        error = classify(response)
        assert isinstance(error, NotFoundError)
        assert not isinstance(error, NoDataForYear), url


def test_valid_codes_without_data_answer_200_with_an_empty_list() -> None:
    response = recorded("PSDData_GetCountryCommodityDataByYear", "no_data_valid_codes")
    assert (response.status_code, response.json()) == (200, [])
    assert classify(response) is None


def test_the_gateway_not_found_is_a_not_found_error() -> None:
    """NOT RECORDED: api.data.gov's documented NOT_FOUND body."""
    body = {
        "error": {
            "code": "NOT_FOUND",
            "message": "The requested URL was not found on this server.",
        }
    }
    error = classify(synthesised(404, body))
    assert isinstance(error, NotFoundError)
    assert not isinstance(error, NoDataForYear), "a wrong request, not an empty year"
    assert "no route for /api/psd/commodities" in error.message


def test_other_statuses_fall_through_to_core() -> None:
    assert classify(synthesised(500, {"Message": "An error has occurred."})) is None
    assert classify(recorded("PSDData_GetCommodities", "all")) is None


def test_the_recorded_429_is_a_rate_limit_error_with_its_retry_after() -> None:
    response = recorded("PSDData_GetCommodities", "over_rate_limit")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "3151"
    assert response.headers["x-ratelimit-limit"] == "1000"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert response.json()["error"]["code"] == "OVER_RATE_LIMIT"
    error = classify(response)
    assert isinstance(error, RateLimitError)
    assert error.retry_after == 3151.0
    assert "OVER_RATE_LIMIT: You have exceeded your rate limit" in error.message
    assert "1000 requests per rolling hour per key" in error.message
    assert "should be back at" in error.message
    assert "retry after" not in error.message, "core's adapters append the retry hint"
    assert "0 of 1000 requests left" in error.message
    assert API_KEY_ENV in error.message
    snapshot = quota()
    assert snapshot is not None
    assert (snapshot.limit, snapshot.remaining, snapshot.retry_after) == (1000, 0, 3151.0)


@pytest.mark.anyio
async def test_the_wrapper_raises_once_on_the_recorded_429_and_refuses_the_next(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Retry-After 3151 s is beyond ``backoff_max``: core does not retry, the caller gets
    the error, and the next request is refused before it is sent."""
    route = replay_fixture("PSDData_GetCommodities", "over_rate_limit")
    with pytest.raises(RateLimitError) as info:
        await api.PSDData_GetCommodities()
    assert info.value.retry_after == 3151.0
    assert route.call_count == 1
    with pytest.raises(RateLimitError, match="Nothing was sent") as refused:
        await api.PSDData_GetRegions()
    assert refused.value.retry_after is not None
    assert 3140 <= refused.value.retry_after <= 3151
    assert route.call_count == 1


def test_429_without_retry_after_falls_back_to_the_quota_window() -> None:
    """NOT RECORDED: the recorded body without Retry-After or quota headers."""
    error = classify(synthesised(429, OVER_RATE_LIMIT))
    assert isinstance(error, RateLimitError)
    assert error.retry_after == QUOTA_WINDOW == 3600.0
    assert "an hourly quota per key" in error.message, "no limit known, none invented"
    assert "should be back at" in error.message
    snapshot = quota()
    assert snapshot is not None
    assert snapshot.remaining == 0


@pytest.mark.anyio
@pytest.mark.parametrize(("retry_after", "attempts"), [("3151", 1), (None, 4)])
async def test_core_retries_a_429_only_within_its_backoff(
    respx_mock: respx.MockRouter, retry_after: str | None, attempts: int
) -> None:
    """A ``Retry-After`` beyond ``backoff_max`` (30 s), as recorded, stops core's retries;
    without one (NOT RECORDED) core retries three times at its short backoff, each
    another call, and the caller then gets ``RateLimitError`` with the one-hour
    fallback."""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    headers = {"Retry-After": retry_after} if retry_after else {}
    route = respx_mock.get(f"{BASE_URL}/api/psd/commodities").mock(
        return_value=httpx.Response(429, json=OVER_RATE_LIMIT, headers=headers)
    )
    quick = QuotaAwareClient(dataclasses.replace(config, rate_limit=None), sleep=fake_sleep)
    with pytest.raises(RateLimitError) as info:
        await quick.get_json("/api/psd/commodities")
    assert info.value.retry_after == float(retry_after or 3600)
    assert route.call_count == attempts
    assert all(seconds <= RetryPolicy().backoff_max for seconds in sleeps)


def test_quota_headers_land_in_the_snapshot() -> None:
    assert quota() is None
    observe_quota(recorded("PSDData_GetCommodities", "all"), now=NOW)
    snapshot = quota()
    assert snapshot is not None
    assert (snapshot.limit, snapshot.remaining, snapshot.observed_at) == (1000, 999, NOW)
    assert snapshot.resumes_at is None
    assert snapshot.describe() == (
        "999 of 1000 requests left in the rolling hour (as of 2026-10-23T08:00:00Z)"
    )


def test_an_answer_without_quota_headers_leaves_the_snapshot() -> None:
    observe_quota(recorded("PSDData_GetCommodities", "all"), now=NOW)
    observe_quota(recorded("PSDData_GetCommodities", "invalid_key"))
    snapshot = quota()
    assert snapshot is not None
    assert (snapshot.remaining, snapshot.observed_at) == (999, NOW)


def test_the_snapshot_is_read_only() -> None:
    observe_quota(recorded("PSDData_GetCommodities", "all"), now=NOW)
    snapshot = quota()
    assert snapshot is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.remaining = 5  # type: ignore[misc]


def test_a_spent_quota_pauses_for_the_window_or_retry_after() -> None:
    observe_quota(
        synthesised(200, [], {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "0"}), now=NOW
    )
    assert quota_pause(now=NOW) == QUOTA_WINDOW
    assert quota_pause(now=NOW + timedelta(minutes=59)) == 60.0
    assert quota_pause(now=NOW + timedelta(hours=2)) == 0.0
    observe_quota(synthesised(429, OVER_RATE_LIMIT, {"Retry-After": "90"}), now=NOW)
    snapshot = quota()
    assert snapshot is not None
    assert (snapshot.limit, snapshot.remaining, snapshot.retry_after) == (1000, 0, 90.0)
    assert quota_pause(now=NOW + timedelta(seconds=30)) == 60.0


@pytest.mark.anyio
async def test_a_spent_quota_beyond_backoff_max_is_refused_without_sending(
    respx_mock: respx.MockRouter,
) -> None:
    """The last answer left 0 and the gateway names no time: the next request would have
    to wait an hour, longer than ``backoff_max``, so it raises instead of hanging."""
    events: list[str] = []

    async def fake_sleep(seconds: float) -> None:
        events.append(f"sleep {seconds:.0f}")

    def respond(request: httpx.Request) -> httpx.Response:
        events.append("sent")
        headers = {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "0"}
        return httpx.Response(200, json=[], headers=headers)

    route = respx_mock.get(f"{BASE_URL}/api/psd/regions").mock(side_effect=respond)
    paced = QuotaAwareClient(dataclasses.replace(config, rate_limit=None), sleep=fake_sleep)
    assert await paced.get_json("/api/psd/regions") == []
    with pytest.raises(RateLimitError) as info:
        await paced.get_json("/api/psd/regions")
    assert events == ["sent"], "nothing sent, nothing slept"
    assert route.call_count == 1
    assert info.value.retry_after is not None
    assert 3590 <= info.value.retry_after <= 3600
    assert "0 of 1000 requests left" in info.value.message
    assert "Nothing was sent: the quota should be back at" in info.value.message
    assert "retry after" not in info.value.message, "core's adapters append the retry hint"
    assert error_to_text(info.value).endswith("(retry after 3600 s)") or error_to_text(
        info.value
    ).endswith("(retry after 3599 s)")


@pytest.mark.anyio
async def test_a_spent_quota_within_backoff_max_is_waited_out(
    respx_mock: respx.MockRouter,
) -> None:
    """NOT RECORDED: the recorded body naming 20 s; the next request sleeps, then is sent."""
    events: list[str] = []

    async def fake_sleep(seconds: float) -> None:
        events.append(f"sleep {seconds:.0f}")

    answers = iter(
        [
            httpx.Response(429, json=OVER_RATE_LIMIT, headers={"Retry-After": "20"}),
            httpx.Response(
                200, json=[], headers={"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "999"}
            ),
        ]
    )

    def respond(request: httpx.Request) -> httpx.Response:
        events.append("sent")
        return next(answers)

    respx_mock.get(f"{BASE_URL}/api/psd/regions").mock(side_effect=respond)
    paced = QuotaAwareClient(
        dataclasses.replace(config, rate_limit=None, retry=RetryPolicy(max_attempts=1)),
        sleep=fake_sleep,
    )
    with pytest.raises(RateLimitError):
        await paced.get_json("/api/psd/regions")
    assert await paced.get_json("/api/psd/regions") == []
    assert events[0] == "sent"
    assert events[1] in {"sleep 20", "sleep 19"}
    assert events[2] == "sent"
    snapshot = quota()
    assert snapshot is not None
    assert snapshot.remaining == 999
    assert quota_pause() == 0.0


@pytest.mark.anyio
async def test_the_bound_is_the_clients_backoff_max(respx_mock: respx.MockRouter) -> None:
    """A long-running script that would rather wait raises ``backoff_max`` in its config."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    respx_mock.get(f"{BASE_URL}/api/psd/regions").mock(
        return_value=httpx.Response(
            200, json=[], headers={"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "999"}
        )
    )
    observe_quota(synthesised(200, [], {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "0"}))
    patient = QuotaAwareClient(
        dataclasses.replace(config, rate_limit=None, retry=RetryPolicy(backoff_max=7200.0)),
        sleep=fake_sleep,
    )
    assert await patient.get_json("/api/psd/regions") == []
    assert len(slept) == 1
    assert 3590 <= slept[0] <= 3600


@pytest.mark.anyio
async def test_unraised_answers_update_the_snapshot_too(respx_mock: respx.MockRouter) -> None:
    """The recorder asks for raw answers (``raise_on_error=False``), which skip ``classify``."""
    headers = {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "42"}
    respx_mock.get(f"{BASE_URL}/api/psd/regions").mock(
        return_value=httpx.Response(500, json={}, headers=headers)
    )
    quick = QuotaAwareClient(
        dataclasses.replace(config, rate_limit=None, retry=RetryPolicy(max_attempts=1))
    )
    response = await quick.request("GET", "/api/psd/regions", raise_on_error=False)
    assert response.status_code == 500
    snapshot = quota()
    assert snapshot is not None
    assert snapshot.remaining == 42
    with pytest.raises(UpstreamError):
        await quick.get_json("/api/psd/regions")


def test_the_recorded_bodies_are_the_documented_shapes() -> None:
    """The bad-key answer carries api.data.gov's error object and no quota headers."""
    response = recorded("PSDData_GetCommodities", "invalid_key")
    body = json.loads(response.text)
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert "x-ratelimit-remaining" not in response.headers
    listed = recorded("PSDData_GetCommodities", "all")
    assert listed.headers["x-ratelimit-limit"] == "1000"


def _cached_client(sleep: Callable[[float], Awaitable[None]]) -> QuotaAwareClient:
    cached = dataclasses.replace(config, rate_limit=None, cache=MemoryCache(ttl=None))
    return QuotaAwareClient(cached, sleep=sleep)


@pytest.mark.anyio
async def test_a_cache_hit_is_served_while_the_quota_is_spent(
    respx_mock: respx.MockRouter,
) -> None:
    """B1: the gate never refuses or delays what the cache can answer; it costs no quota."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    spent = {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "0"}
    route = respx_mock.get(f"{BASE_URL}/api/psd/regions").mock(
        return_value=httpx.Response(200, json=[{"regionCode": "R00"}], headers=spent)
    )
    other = respx_mock.get(f"{BASE_URL}/api/psd/countries").mock(
        return_value=httpx.Response(200, json=[])
    )
    paced = _cached_client(fake_sleep)
    first = await paced.get_json("/api/psd/regions")
    assert quota_pause() > RetryPolicy().backoff_max, "the quota is spent"
    assert await paced.get_json("/api/psd/regions") == first
    raw = await paced.request("GET", "/api/psd/regions", raise_on_error=False)
    assert raw.extensions.get("xippios_cache") == "hit"
    assert route.call_count == 1
    assert slept == []
    with pytest.raises(RateLimitError, match="Nothing was sent"):
        await paced.get_json("/api/psd/countries")
    assert other.call_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize("raw", [False, True], ids=["get_json", "raise_on_error=False"])
async def test_a_cache_hit_never_updates_the_quota(respx_mock: respx.MockRouter, raw: bool) -> None:
    """ADR-0010: quota headers are never taken from a cache hit; they are as old as the entry."""

    async def no_sleep(seconds: float) -> None:
        raise AssertionError(f"slept {seconds}")

    path = "/api/psd/regions"
    respx_mock.get(f"{BASE_URL}{path}").mock(
        return_value=httpx.Response(
            200, json=[], headers={"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "5"}
        )
    )
    paced = _cached_client(no_sleep)
    await paced.get_json(path)
    first = quota()
    assert first is not None
    assert first.remaining == 5
    observe_quota(recorded("PSDData_GetCommodities", "all"), now=NOW)
    if raw:
        hit = await paced.request("GET", path, raise_on_error=False)
        assert hit.extensions.get("xippios_cache") == "hit"
    else:
        await paced.get_json(path)
    snapshot = quota()
    assert snapshot is not None
    assert (snapshot.remaining, snapshot.observed_at) == (999, NOW)


def test_the_client_asks_for_json() -> None:
    """The snapshot's operations produce JSON and XML; httpx alone sends ``Accept: */*``."""
    assert config.headers == {"Accept": "application/json"}
