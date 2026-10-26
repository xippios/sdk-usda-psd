"""The client's error mapping, and core's quota policy wired to the gateway's answers.

Recorded answers come from ``tests/fixtures``, the gateway's 429 included
(``PSDData_GetCommodities/over_rate_limit.json``, recorded after spending the key's
hourly quota on 2026-10-23). Cases the recordings do not cover (the gateway's
``NOT_FOUND`` 404, the other ``API_KEY_*`` codes, a 429 without ``Retry-After``) are
built in the recorded body's shape and say so. The quota policy itself is core's
(``QuotaPolicy``, ADR-0015) and is tested there; this module checks that the package
installs it on the gateway's headers, that it reads the recorded 429, and that ``classify``
shapes core's retries of a 429.
"""

import dataclasses
import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx
from xippios.core import AsyncClient, AuthError, NotFoundError, RateLimitError, RetryPolicy
from xippios.core.testing import load_fixture

from xippios.usda.psd import api
from xippios.usda.psd._client import (
    API_KEY_ENV,
    BASE_URL,
    RATE_LIMIT,
    auth,
    classify,
    client,
    config,
    policy,
)
from xippios.usda.psd.errors import NoDataForYear

FIXTURES = Path(__file__).parent / "fixtures"
DATA = "PSDData_GetCountryCommodityDataByYear"


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


RECORDED_429 = load_fixture(FIXTURES / "PSDData_GetCommodities" / "over_rate_limit.json").response
"""The recorded 429: ``Retry-After: 3151``, ``x-ratelimit-remaining: 0``."""
OVER_RATE_LIMIT = json.loads(RECORDED_429.body)
"""The recorded 429 body, for the variants built around it."""


def test_the_client_is_wired_for_the_gateway() -> None:
    """One request per second, psd's classify, and core's quota policy on api.data.gov's
    ``x-ratelimit-*`` headers, which count the rolling hour, not a pace; the gateway sends
    no reset header, so one hour is the fallback wait (ADR-0010, ADR-0015)."""
    assert (RATE_LIMIT.per_minute, RATE_LIMIT.capacity) == (60, 1)
    assert config.rate_limit is RATE_LIMIT
    assert config.classify is classify
    assert client.config is config
    assert config.observe == policy.observe, "installed: every answer reaches the policy"
    assert config.before_request is not None
    assert (policy.limit_header, policy.remaining_header, policy.reset_header) == (
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        None,
    )
    assert (policy.window, policy.source) == (3600.0, "usda-psd")
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
    assert "api.fas.usda.gov" not in error.message, "host-free (conventions §5)"
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
    assert "api.fas.usda.gov" not in error.message, "host-free (conventions §5)"
    assert "expected back in 3151 s" in error.message, "no snapshot without the client"
    assert "Nothing was retried" in error.message
    assert "retry after" not in error.message, "core's adapters append the retry hint"
    assert API_KEY_ENV in error.message


@pytest.mark.anyio
@pytest.mark.rate_limited
async def test_the_policy_reads_the_recorded_429_through_core(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The recorded 429 through the package's client: core's ``observe`` marks the quota
    spent until its ``Retry-After``, ``classify`` raises after one request (3151 s is beyond
    ``backoff_max``), and the next request is refused before it is sent. Marked
    ``rate_limited``: the refusal is the policy's pause, which the plugin turns off."""
    route = replay_fixture("PSDData_GetCommodities", "over_rate_limit")
    with pytest.raises(RateLimitError) as info:
        await api.PSDData_GetCommodities()
    assert info.value.retry_after == 3151.0
    assert route.call_count == 1, "not retried"
    assert "1000 requests per rolling hour per key" in info.value.message
    assert "0 of 1000 requests left" in info.value.message
    snapshot = policy.snapshot()
    assert snapshot is not None
    assert (snapshot.limit, snapshot.remaining) == (1000, 0)
    assert snapshot.resumes_at == snapshot.observed_at + timedelta(seconds=3151)
    with pytest.raises(RateLimitError, match="nothing was sent") as refused:
        await api.PSDData_GetRegions()
    assert refused.value.retry_after is not None
    assert 3140 <= refused.value.retry_after <= 3151
    assert route.call_count == 1


def test_429_without_retry_after_falls_back_to_the_quota_window() -> None:
    """NOT RECORDED: the recorded body without Retry-After or quota headers."""
    error = classify(synthesised(429, OVER_RATE_LIMIT))
    assert isinstance(error, RateLimitError)
    assert error.retry_after == policy.window == 3600.0
    assert "an hourly quota per key" in error.message, "no limit known, none invented"
    assert "expected back in 3600 s" in error.message


def _recorded_429(retry_after: str | None) -> httpx.Response:
    """The recorded 429 with ``Retry-After: 3151``; with ``None``, NOT A RECORDING: the same
    answer, body and quota headers, with its ``Retry-After`` dropped."""
    headers = [
        (name, value)
        for name, value in RECORDED_429.headers
        if retry_after is not None or name.lower() != "retry-after"
    ]
    assert dict(headers).get("retry-after") == retry_after
    return httpx.Response(RECORDED_429.status, headers=headers, content=RECORDED_429.content)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("retry_after", "shaped", "attempts"),
    [("3151", True, 1), (None, True, 1), (None, False, 4)],
    ids=["recorded", "without_retry_after", "control_without_classify"],
)
async def test_core_retries_a_429_only_within_its_backoff(
    respx_mock: respx.MockRouter, retry_after: str | None, shaped: bool, attempts: int
) -> None:
    """psd's ``classify`` shapes core's retries (ADR-0015): its ``RateLimitError`` carries the
    wait, the recorded ``Retry-After`` or else the one-hour window, beyond ``backoff_max``
    (30 s), so a 429 is sent once, with or without the header. The control drops
    ``classify``: core then retries the 429 without ``Retry-After`` on its status alone,
    three more times at its short backoff, so this test fails if ``classify`` stops
    shaping the retries."""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    route = respx_mock.get(f"{BASE_URL}/api/psd/commodities").mock(
        return_value=_recorded_429(retry_after)
    )
    quick = dataclasses.replace(config, rate_limit=None)
    if not shaped:
        quick = dataclasses.replace(quick, classify=None)
    with pytest.raises(RateLimitError) as info:
        await AsyncClient(quick, sleep=fake_sleep).get_json("/api/psd/commodities")
    assert route.call_count == attempts
    assert len(sleeps) == attempts - 1
    assert all(seconds <= RetryPolicy().backoff_max for seconds in sleeps)
    if shaped:
        assert info.value.retry_after == float(retry_after or 3600)
    else:
        assert info.value.retry_after is None, "core's own mapping: no Retry-After, no wait"


def test_the_recorded_bodies_are_the_documented_shapes() -> None:
    """The bad-key answer carries api.data.gov's error object and no quota headers."""
    response = recorded("PSDData_GetCommodities", "invalid_key")
    body = json.loads(response.text)
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert "x-ratelimit-remaining" not in response.headers
    listed = recorded("PSDData_GetCommodities", "all")
    assert listed.headers["x-ratelimit-limit"] == "1000"


def test_the_client_asks_for_json() -> None:
    """The snapshot's operations produce JSON and XML; httpx alone sends ``Accept: */*``."""
    assert config.headers == {"Accept": "application/json"}
