"""Structural checks every task must satisfy. Per-task tests with recorded fixtures go below."""

import inspect
import os
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx
from xippios.core import InvalidRequestError, NotFoundError
from xippios.core.testing import mcp_call

from xippios.usda.psd import __version__, tasks
from xippios.usda.psd._client import API_KEY_ENV, BASE_URL, auth
from xippios.usda.psd.enums import AttributeId, UnitId
from xippios.usda.psd.errors import UnknownCode
from xippios.usda.psd.mcp import server

SHELL_KEY = os.environ.get(API_KEY_ENV)
"""The key the shell held when the tests were collected, before any fixture; never printed."""

TASKS = [getattr(tasks, name) for name in tasks.__all__]


def test_package_has_a_version() -> None:
    assert __version__


def test_replay_tests_send_the_placeholder_key(placeholder_api_key: str | None) -> None:
    """A request sent outside a live test carries the placeholder, never the shell's key.

    Every assertion is on a boolean, so a failure says where the key went, never the key.
    """
    assert placeholder_api_key is not None
    env_holds_placeholder = os.environ[API_KEY_ENV] == placeholder_api_key
    assert env_holds_placeholder, f"{API_KEY_ENV} does not hold the placeholder"
    sent = next(auth.sync_auth_flow(httpx.Request("GET", BASE_URL)))
    carried = sent.headers.get(auth.header, "")
    where = f"the {auth.header} header"
    sends_placeholder = carried == placeholder_api_key
    assert sends_placeholder, f"{where} does not carry the placeholder"
    if SHELL_KEY and placeholder_api_key != SHELL_KEY:
        outgoing = [str(sent.url), *sent.headers.values(), carried]
        leaked = any(SHELL_KEY in part for part in outgoing)
        assert not leaked, f"the key in {API_KEY_ENV} went out with the request"


@pytest.mark.parametrize("task", TASKS, ids=tasks.__all__)
def test_task_is_a_sync_facade_with_an_agent_docstring(task: object) -> None:
    assert callable(task)
    assert hasattr(task, "async_fn"), "write the async function and derive the sync one with sync()"
    doc = inspect.getdoc(task) or ""
    assert doc, "task functions need a docstring: agents read it"
    assert doc.splitlines()[0].endswith("."), "the first line is one sentence"
    if inspect.signature(task).parameters:
        assert "Args:" in doc, "explain every parameter under Args: with valid-value examples"


WHEAT, CORN, SOYBEANS = "0410000", "0440000", "2222000"
DATA = "PSDData_GetCountryCommodityDataByYear"
ALL = "PSDData_GetCommodityDataByYear"
WORLD = "PSDData_GetWorldCommodityDataByYear"
RELEASES = "PSDData_GetDataReleaseInfo"


def test_get_data_for_one_country(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    data = replay_fixture(DATA, "wheat_us_2023")
    releases = replay_fixture(RELEASES, "wheat")
    result = tasks.get_data(WHEAT, 2023, "US")
    assert (data.call_count, releases.call_count) == (1, 1)
    assert len(result.data) == 15
    production = next(r for r in result.data if r.attribute_id == AttributeId.PRODUCTION)
    assert production.value == Decimal("49095.0")
    assert production.unit_id == UnitId._1000_MT
    assert result.meta.source == "usda-psd"
    assert result.meta.endpoint == "PSDData_GetCountryCommodityDataByYear"
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 2023,
        "country_code": "US",
    }
    assert result.meta.vintage is None


def test_published_at_is_the_release_month_of_the_country_and_year(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """US wheat 2023 was last revised in the July 2026 release; the records say the same."""
    replay_fixture(DATA, "wheat_us_2023")
    replay_fixture(RELEASES, "wheat")
    result = tasks.get_data(WHEAT, 2023, "US")
    assert result.meta.published_at == datetime(2026, 7, 1, tzinfo=UTC)
    assert {(r.calendar_year, r.month) for r in result.data} == {(2026, 7)}


def test_get_data_for_every_country(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    """``country/all``: each country's records carry its own release month, and
    ``published_at`` is the latest of them."""
    replay_fixture(ALL, "wheat_all_2023")
    replay_fixture(RELEASES, "wheat")
    result = tasks.get_data(WHEAT, 2023)
    assert result.meta.endpoint == "PSDData_GetCommodityDataByYear"
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 2023,
        "country_code": None,
    }
    assert len(result.data) == 1845
    assert result.meta.published_at == datetime(2026, 10, 1, tzinfo=UTC)
    releases = {
        r.country_code: (r.release_year, r.release_month)
        for r in tasks.get_release_dates(WHEAT).data
        if r.market_year == 2023
    }
    assert {r.country_code: (r.calendar_year, r.month) for r in result.data} == releases


def test_get_world_data(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    world = replay_fixture(WORLD, "wheat_world_2023")
    replay_fixture(RELEASES, "wheat")
    result = tasks.get_world_data(WHEAT, 2023)
    assert world.call_count == 1
    assert result.meta.endpoint == "PSDData_GetWorldCommodityDataByYear"
    assert result.meta.request == {"commodity_code": WHEAT, "market_year": 2023}
    assert len(result.data) == 15
    assert {r.country_code for r in result.data} == {"00"}
    assert result.meta.published_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert {(r.calendar_year, r.month) for r in result.data} == {(2026, 10)}


def test_release_dates_are_fetched_once_for_several_data_calls(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture(DATA, "wheat_us_2023")
    replay_fixture(WORLD, "wheat_world_2023")
    releases = replay_fixture(RELEASES, "wheat")
    tasks.get_data(WHEAT, 2023, "US")
    tasks.get_world_data(WHEAT, 2023)
    tasks.get_release_dates(WHEAT)
    assert releases.call_count == 1


def test_published_at_is_none_when_the_release_list_lacks_the_year(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture(RELEASES, "wheat")
    releases = tasks.get_release_dates(WHEAT).data
    assert max(r.market_year for r in releases) == 2026
    assert tasks._published_at(releases, 2027, "US") is None
    assert tasks._published_at(releases, 2023, "ZZ") is None
    assert tasks._published_at(releases, 2023, "US") == datetime(2026, 7, 1, tzinfo=UTC)
    assert tasks._published_at([], 2023, None) is None


def test_get_release_dates(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture(RELEASES, "wheat")
    result = tasks.get_release_dates(WHEAT)
    assert len(result.data) == 7754
    assert result.meta.endpoint == "PSDData_GetDataReleaseInfo"
    assert result.meta.request == {"commodity_code": WHEAT}
    assert result.meta.published_at is None
    assert result.meta.vintage is None
    us_2023 = [r for r in result.data if (r.country_code, r.market_year) == ("US", 2023)]
    assert [(r.release_year, r.release_month) for r in us_2023] == [(2026, 7)]


def test_a_market_year_without_data_is_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(DATA, "unknown_year")
    with pytest.raises(NotFoundError) as info:
        tasks.get_data(WHEAT, 1900, "US")
    message = str(info.value)
    assert "commodity 0410000, country US, market year 1900" in message
    assert "upstream answered HTTP 404" in message
    assert route.call_count == 1


def test_unknown_codes_are_refused_before_any_request(respx_mock: respx.MockRouter) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    with pytest.raises(UnknownCode, match="0410000 \\(Wheat\\)"):
        tasks.get_data("0410001", 2023, "US")
    with pytest.raises(UnknownCode, match="'XX' is not a country_code"):
        tasks.get_data(WHEAT, 2023, "XX")
    with pytest.raises(UnknownCode, match="'00' is not a country_code"):
        tasks.get_data(WHEAT, 2023, "00")
    with pytest.raises(UnknownCode):
        tasks.get_world_data("9999999", 2023)
    with pytest.raises(UnknownCode):
        tasks.get_release_dates("wheat")
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_data(WHEAT, 23, "US")
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_mcp_tool_call_end_to_end(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture(DATA, "wheat_us_2023")
    replay_fixture(RELEASES, "wheat")
    payload = await mcp_call(
        server,
        "usda_psd_get_data",
        {"commodity_code": WHEAT, "market_year": 2023, "country_code": "US"},
    )
    assert len(payload["data"]) == 15
    production = next(row for row in payload["data"] if row["attribute_id"] == 28)
    assert production == {
        "commodity_code": "0410000",
        "country_code": "US",
        "market_year": 2023,
        "calendar_year": 2026,
        "month": 7,
        "attribute_id": 28,
        "unit_id": 8,
        "value": 49095.0,
    }
    assert payload["meta"]["endpoint"] == "PSDData_GetCountryCommodityDataByYear"
    assert payload["meta"]["published_at"].startswith("2026-07-01T00:00:00")
    with pytest.raises(AssertionError, match=r"UnknownCode.*0410000 \(Wheat\)"):
        await mcp_call(
            server, "usda_psd_get_data", {"commodity_code": "0410001", "market_year": 2023}
        )


@pytest.mark.anyio
async def test_value_is_a_json_number_through_both_adapters(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """ADR-0008: ``Decimal`` in Python, a JSON number on the wire, never a string."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.psd.http import router

    replay_fixture(WORLD, "wheat_world_2023")
    replay_fixture(RELEASES, "wheat")
    payload = await mcp_call(
        server, "usda_psd_get_world_data", {"commodity_code": WHEAT, "market_year": 2023}
    )
    values = [row["value"] for row in payload["data"]]
    assert values
    assert all(isinstance(value, float) for value in values)
    app = FastAPI()
    app.include_router(router)
    http = TestClient(app)
    response = http.get(
        "/usda-psd/get_world_data", params={"commodity_code": WHEAT, "market_year": 2023}
    )
    assert response.status_code == 200, response.text
    assert [row["value"] for row in response.json()["data"]] == values
    yields = [row["value"] for row in response.json()["data"] if row["attribute_id"] == 184]
    assert yields == [3.5622]
    rejected = http.get(
        "/usda-psd/get_world_data", params={"commodity_code": "0410001", "market_year": 2023}
    )
    assert rejected.status_code == 422
    assert rejected.json()["title"] == "UnknownCode"
