"""The client's wiring and error mapping, and the shared package's api.data.gov gateway on it.

Recorded answers come from ``tests/fixtures``, the gateway's 429 included
(``get_commodities/over_rate_limit.json``, recorded after spending the key's hourly quota on
2026-10-23). The one case the recordings do not cover, the recorded empty 404 with its content
type changed, is of conventions §10's fourth kind, and each test says so. The gateway and its
quota policy are the shared package's (``xippios.usda.fas``'s ``Gateway``, sdk-core ADR-0032,
sdk-core ADR-0037), whose tests hold its own answers: the key's codes, its ``NOT_FOUND``, a 429
classified on its own and core's retries of a 429. This module checks that the package installs
them, that the policy reads the recorded 429 through the package's client, that ``classify``
keeps PSD's own answer after the gateway's, and that the client keeps answers in core's
response cache.
"""

import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx
from xippios.core import Answer, AuthError, EnvVar, MemoryCache, NotFoundError, RateLimitError
from xippios.core.testing import CLOCK_SLACK, load_fixture, response_from_fixture
from xippios.usda.fas import Gateway, NoDataForYear

from xippios.usda.psd import api
from xippios.usda.psd._client import (
    API_KEY_ENV,
    DATA_PATH,
    ENV_VARS,
    RATE_LIMIT,
    SOURCE,
    auth,
    classify,
    client,
    config,
    gateway,
)

FIXTURES = Path(__file__).parent / "fixtures"
DATA = "get_country_commodity_data_by_year"
SLACK = CLOCK_SLACK.total_seconds()
"""A wait read through the client counts from the snapshot to now, a moment later."""


def test_the_client_is_wired_for_the_gateway() -> None:
    """One request per second, psd's classify, and core's gateway: its key auth and its
    one quota policy per process on api.data.gov's ``x-ratelimit-*`` headers, which count
    the rolling hour, not a pace; one hour is the fallback wait (sdk-core ADR-0032,
    sdk-core ADR-0037)."""
    assert (RATE_LIMIT.per_minute, RATE_LIMIT.capacity) == (60, 1)
    assert config.rate_limit is RATE_LIMIT
    assert config.classify is classify
    assert client.config is config
    assert gateway.source == SOURCE == "usda-psd"
    assert gateway.data_path is DATA_PATH, "core maps PSD's empty 404 there (sdk-core#106)"
    assert gateway.policy is Gateway.policy, "one policy per process for the shared key"
    assert config.observe == Gateway.policy.observe, "installed: every answer reaches it"
    assert config.before_request == Gateway.policy.before_request
    assert (Gateway.policy.limit_header, Gateway.policy.remaining_header) == (
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
    )
    assert (Gateway.policy.window, Gateway.policy.source) == (3600.0, "api.data.gov")
    assert auth is gateway.auth
    assert (auth.location, auth.name) == ("header", "X-Api-Key")
    assert auth.env_var == API_KEY_ENV == "DATA_GOV_API_KEY"  # pragma: allowlist secret


def test_env_vars_name_the_one_key_the_package_reads() -> None:
    """``ENV_VARS`` tells a host what to set: the gateway's key, secret and required, and
    nothing else, since the package reads no other variable (conventions §7)."""
    assert (EnvVar(API_KEY_ENV, secret=True, required=True),) == ENV_VARS


@pytest.mark.anyio
async def test_the_wrapper_raises_auth_error_on_the_recorded_invalid_key(
    replay_fixture: Callable[[str, str], respx.Route],
    placeholder_api_key: str,
) -> None:
    route = replay_fixture("get_commodities", "invalid_key")
    with pytest.raises(AuthError, match="API_KEY_INVALID") as info:
        await api.get_commodities()
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
    assert classify(response_from_fixture(load_fixture(FIXTURES / DATA / f"{case}.json"))) is None
    assert (await client.get_answer(path)).payload == []


@pytest.mark.anyio
async def test_a_year_without_data_answers_404_with_an_empty_body(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    response = response_from_fixture(load_fixture(FIXTURES / DATA / "unknown_year.json"))
    assert (response.status_code, response.content) == (404, b"")
    error = classify(response)
    assert isinstance(error, NotFoundError)
    assert "no data for GET /api/psd/commodity/0410000/country/US/year/1900" in error.message
    route = replay_fixture(DATA, "unknown_year")
    with pytest.raises(NotFoundError, match="empty body"):
        await client.get_answer("/api/psd/commodity/0410000/country/US/year/1900")
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("wrapper", "case"),
    [
        ("get_country_commodity_data_by_year", "unknown_year"),
        ("get_commodity_data_by_year", "year_1900"),
        ("get_world_commodity_data_by_year", "year_1900"),
    ],
)
def test_every_data_form_answers_a_year_without_data_with_an_empty_404(
    wrapper: str, case: str
) -> None:
    response = response_from_fixture(load_fixture(FIXTURES / wrapper / f"{case}.json"))
    assert (response.status_code, response.content) == (404, b"")
    assert response.headers["content-type"].startswith("text/plain")
    error = classify(response)
    assert isinstance(error, NoDataForYear), "the shared package's, by the data_path"
    assert isinstance(error, NotFoundError), "in the taxonomy, conventions §5"
    assert error.path == response.request.url.path
    assert error.source == SOURCE
    assert f"no data for GET {error.path} (HTTP 404 with an empty body)" in error.message


def test_the_content_type_is_compared_without_case() -> None:
    """NOT RECORDED as such: the recorded empty 404 at its own URL, its content type
    upper-cased (conventions §10, kind 4: a header replaced). Media types are case-insensitive
    (RFC 9110), so it is still PSD's empty year."""
    fixture = load_fixture(FIXTURES / DATA / "unknown_year.json")
    response = httpx.Response(
        404,
        headers=[("Content-Type", "TEXT/PLAIN; charset=utf-8")],
        content=b"",
        request=httpx.Request("GET", fixture.request.url),
    )
    assert isinstance(classify(response), NoDataForYear)


def test_the_data_path_covers_the_three_data_forms_only() -> None:
    """The gateway says that a year holds no data only on a path of ``DATA_PATH``: one
    country, every country and the world, by market year, never the release list."""
    assert DATA_PATH.fullmatch("/api/psd/commodity/0410000/country/US/year/1900")
    assert DATA_PATH.fullmatch("/api/psd/commodity/0410000/country/all/year/1900")
    assert DATA_PATH.fullmatch("/api/psd/commodity/0410000/world/year/1900")
    assert not DATA_PATH.fullmatch("/api/psd/commodity/0410000/dataReleaseDates")
    assert not DATA_PATH.fullmatch("/api/psd/commodities")


def test_an_empty_404_without_text_plain_is_psds_own_not_found() -> None:
    """NOT RECORDED as such: the recorded empty 404 of 1900 at its own URL, its ``text/plain``
    replaced (conventions §10, kind 4: a header replaced). It is not PSD's answer for an empty
    year, so a series does not pass it over: a plain ``NotFoundError`` that names the request
    by core's ``request_description`` and says the request is wrong, never that the year holds
    no data (https://github.com/xippios/sdk-usda-psd/issues/50). Off a data path nothing is
    served: no other operation was seen answering an empty 404, so that half rests on the
    gateway's ``data_path`` above."""
    response = response_from_fixture(load_fixture(FIXTURES / DATA / "unknown_year.json"))
    response.headers["content-type"] = "application/json"
    error = classify(response)
    assert isinstance(error, NotFoundError)
    assert not isinstance(error, NoDataForYear)
    assert error.source == SOURCE
    assert error.message == (
        "PSD Online answered GET /api/psd/commodity/0410000/country/US/year/1900 with HTTP 404 "
        "and an empty body, not as it answers a market year without data on a data path: the "
        "request is wrong, not the year."
    )
    assert "no data" not in error.message
    assert "api.fas.usda.gov" not in error.message, "host-free (conventions §5)"


def test_the_client_keeps_answers_in_cores_cache() -> None:
    """A read-only source of public data keeps upstream's answers in core's response cache,
    at core's default lifetime, every path for 300 s (conventions §6; sdk-core ADR-0061,
    decision 11)."""
    assert isinstance(config.cache, MemoryCache)
    assert dict(config.cache.lifetimes) == {"/": 300.0}


@pytest.mark.anyio
async def test_a_second_read_of_a_path_is_answered_from_the_cache(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Wheat's release list, the largest answer, is sent once: the second read is the
    cache's, with the time its entry was stored (sdk-core ADR-0037, decision 5)."""
    route = replay_fixture("get_data_release_info", "wheat")
    first = await api.get_data_release_info("0410000")
    second = await api.get_data_release_info("0410000")
    assert isinstance(first, Answer)
    assert route.call_count == 1
    assert second.retrieved_at == first.retrieved_at
    assert second.payload == first.payload


def test_valid_codes_without_data_answer_200_with_an_empty_list() -> None:
    response = response_from_fixture(load_fixture(FIXTURES / DATA / "no_data_valid_codes.json"))
    assert (response.status_code, response.json()) == (200, [])
    assert classify(response) is None


@pytest.mark.anyio
@pytest.mark.rate_limited
async def test_the_policy_reads_the_recorded_429_through_core(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The recorded 429 through the package's client: ``Gateway.policy``'s ``observe``
    marks the quota spent until its ``Retry-After``, ``classify`` raises after one request
    (3151 s is beyond ``backoff_max``) with the snapshot's wait from now, and the next
    request is refused before it is sent, in the gateway's name. Marked ``rate_limited``:
    the refusal is the policy's pause, which the plugin turns off."""
    route = replay_fixture("get_commodities", "over_rate_limit")
    with pytest.raises(RateLimitError) as info:
        await api.get_commodities()
    assert info.value.retry_after is not None
    assert 3151 - SLACK <= info.value.retry_after <= 3151
    assert info.value.source == SOURCE
    assert route.call_count == 1, "not retried"
    assert "1000 requests per rolling hour per key" in info.value.message
    assert "0 of 1000 requests left" in info.value.message
    snapshot = Gateway.policy.snapshot()
    assert snapshot is not None
    assert (snapshot.limit, snapshot.remaining) == (1000, 0)
    assert snapshot.resumes_at == snapshot.observed_at + timedelta(seconds=3151)
    with pytest.raises(RateLimitError, match="nothing was sent") as refused:
        await api.get_regions()
    assert refused.value.source == "api.data.gov", "the gateway's quota, not psd's"
    assert "quota spent (" in refused.value.message, "core's words, the source the policy's"
    assert API_KEY_ENV not in refused.value.message
    assert refused.value.retry_after is not None
    assert 3151 - SLACK <= refused.value.retry_after <= 3151
    assert route.call_count == 1


def test_the_recorded_bodies_are_the_documented_shapes() -> None:
    """The bad-key answer carries api.data.gov's error object and no quota headers."""
    response = response_from_fixture(
        load_fixture(FIXTURES / "get_commodities" / "invalid_key.json")
    )
    body = json.loads(response.text)
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert "x-ratelimit-remaining" not in response.headers
    listed = response_from_fixture(load_fixture(FIXTURES / "get_commodities" / "all.json"))
    assert listed.headers["x-ratelimit-limit"] == "1000"


def test_the_client_asks_for_json() -> None:
    """The snapshot's operations produce JSON and XML; httpx alone sends ``Accept: */*``."""
    assert config.headers == {"Accept": "application/json"}
