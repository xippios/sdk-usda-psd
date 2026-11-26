"""The time series: one country's records of a commodity over a range of market years.

Each test replays recorded answers and checks that the series puts together and orders
upstream's records without changing one (sdk-core ADR-0028). ``_recorded`` parses a fixture the
way the wrapper does, without a call, so a test can compare with what upstream sent while
still counting the task's own requests.
"""

import dataclasses
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from xippios.core import InvalidRequestError, NotFoundError, UnknownCode, parse
from xippios.core.testing import (
    ReplayFixture,
    fixture_path,
    load_fixture,
    mcp_call,
    mcp_call_text,
)
from xippios.usda.fas import NoDataForYear

from xippios.usda.psd import tasks
from xippios.usda.psd.enums import AttributeId
from xippios.usda.psd.mcp import server
from xippios.usda.psd.models import CommodityData

FIXTURES = Path(__file__).parent / "fixtures"
WHEAT = "0410000"
DATA = "get_country_commodity_data_by_year"


def _recorded[T](directory: str, case: str, kind: type[list[T]]) -> list[T]:
    """The recorded answer parsed as the wrapper parses it, without a request: under the
    verbatim operation id, so a parse failure names upstream's operation."""
    body = json.loads(load_fixture(fixture_path(FIXTURES, directory, case)).response.body)
    return parse(kind, body, source="usda-psd", endpoint="PSDData_GetCountryCommodityDataByYear")


def _path(market_year: int, country_code: str = "US", commodity_code: str = WHEAT) -> str:
    return f"/api/psd/commodity/{commodity_code}/country/{country_code}/year/{market_year}"


def test_get_time_series_one_request_per_year_in_order(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    routes = {year: replay_fixture(DATA, f"wheat_us_{year}") for year in (2021, 2022, 2023)}
    result = tasks.get_time_series(WHEAT, "US", 2021, 2023, AttributeId.PRODUCTION)
    assert {year: route.call_count for year, route in routes.items()} == {
        2021: 1,
        2022: 1,
        2023: 1,
    }
    assert [call.request.url.path for call in respx_mock.calls] == [
        _path(2021),
        _path(2022),
        _path(2023),
    ], "one request per market year, oldest first"
    assert [r.market_year for r in result.data] == [2021, 2022, 2023]
    for year, record in zip((2021, 2022, 2023), result.data, strict=True):
        recorded = _recorded(DATA, f"wheat_us_{year}", list[CommodityData])
        assert [r for r in recorded if r.attribute_id == 28] == [record], "as upstream sent it"
    assert [r.value for r in result.data] == [
        Decimal("44804.0"),
        Decimal("44898.0"),
        Decimal("49095.0"),
    ]
    assert result.meta.endpoint == "PSDData_GetCountryCommodityDataByYear"
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "country_code": "US",
        "attribute_id": 28,
        "start_year": 2021,
        "end_year": 2023,
    }
    assert result.meta.vintage == "2026-07"
    assert result.meta.published_at is None


def test_time_series_leaves_a_year_without_data_out(
    replay_fixture: ReplayFixture,
    respx_mock: respx.MockRouter,
) -> None:
    """2022 answers PSD's 404 for a year without data: the recorded 1900 answer (empty
    body, ``text/plain``), served at the 2022 path, a recorded answer moved, not a
    hand-written one. The year is absent, nothing filled."""
    absent = load_fixture(fixture_path(FIXTURES, DATA, "unknown_year"))
    assert (absent.response.status, absent.response.content) == (404, b""), "PSD's empty 404"
    replay_fixture(DATA, "wheat_us_2021")
    replay_fixture(DATA, "wheat_us_2023")
    missing = replay_fixture(DATA, "unknown_year", url=f"https://api.fas.usda.gov{_path(2022)}")
    result = tasks.get_time_series(WHEAT, "US", 2021, 2023, AttributeId.EXPORTS)
    assert missing.call_count == 1
    assert len(respx_mock.calls) == 3
    assert [(r.market_year, r.value) for r in result.data] == [
        (2021, Decimal("21656.0")),
        (2023, Decimal("19212.0")),
    ]
    assert result.meta.vintage == "2026-07"


def test_a_series_without_any_record_is_empty_not_an_error(replay_fixture: ReplayFixture) -> None:
    """The recorded empty 404 for 1900 at the 1960 path: the first year a series may ask
    for is accepted, it is absent, and the series is a valid empty list."""
    absent = load_fixture(fixture_path(FIXTURES, DATA, "unknown_year"))
    assert (absent.response.status, absent.response.content) == (404, b""), "PSD's empty 404"
    route = replay_fixture(DATA, "unknown_year", url=f"https://api.fas.usda.gov{_path(1960)}")
    result = tasks.get_time_series(WHEAT, "US", 1960, 1960, AttributeId.PRODUCTION)
    assert result.data == []
    assert (result.meta.vintage, result.meta.published_at) == (None, None)
    assert route.call_count == 1


def test_the_gateways_not_found_inside_a_series_is_raised(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    """NOT A RECORDING: api.data.gov's documented ``NOT_FOUND`` body, the shape
    ``test_client.py`` synthesises, at the 2022 path. It says the request is wrong, not
    that the year is empty, so the series stops there instead of skipping the year."""
    replay_fixture(DATA, "wheat_us_2021")
    later = replay_fixture(DATA, "wheat_us_2023")
    gateway = respx_mock.get(f"https://api.fas.usda.gov{_path(2022)}").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "The requested URL was not found on this server.",
                }
            },
        )
    )
    with pytest.raises(NotFoundError) as info:
        tasks.get_time_series(WHEAT, "US", 2021, 2023, AttributeId.PRODUCTION)
    assert not isinstance(info.value, NoDataForYear)
    assert f"api.data.gov has no route for GET {_path(2022)}" in str(info.value)
    assert gateway.call_count == 1
    assert later.call_count == 0, "nothing after the error is requested"


def test_a_series_may_span_exactly_the_bound(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound counts market years, ends included: with it lowered to 3, 2021 to 2023 is
    asked for and 2021 to 2024 refused before any request. The real bound is 100."""
    assert tasks.SERIES_MAX_YEARS == 100
    monkeypatch.setattr(tasks, "SERIES_MAX_YEARS", 3)
    with pytest.raises(InvalidRequestError, match="2021 to 2024 is 4 market years"):
        tasks.get_time_series(WHEAT, "US", 2021, 2024, AttributeId.PRODUCTION)
    assert not respx_mock.calls
    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    result = tasks.get_time_series(WHEAT, "US", 2021, 2023, AttributeId.PRODUCTION)
    assert [r.market_year for r in result.data] == [2021, 2022, 2023]


def test_a_series_of_an_attribute_the_answers_lack_is_empty(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    """Area Planted (1) is a packaged attribute that wheat US does not report."""
    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    result = tasks.get_time_series(WHEAT, "US", 2021, 2023, AttributeId.AREA_PLANTED)
    assert result.data == []
    assert result.meta.vintage is None
    assert len(respx_mock.calls) == 3


@pytest.mark.anyio
async def test_time_series_tool_end_to_end(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    arguments: dict[str, Any] = {
        "commodity_code": WHEAT,
        "country_code": "US",
        "attribute_id": 28,
        "start_year": 2021,
        "end_year": 2023,
    }
    payload = await mcp_call(server, "usda_psd_get_time_series", arguments)
    assert [(row["market_year"], row["value"]) for row in payload["data"]] == [
        (2021, 44804.0),
        (2022, 44898.0),
        (2023, 49095.0),
    ]
    assert payload["meta"]["request"] == arguments
    assert payload["meta"]["vintage"] == "2026-07"
    with pytest.raises(AssertionError, match="InvalidRequestError: start_year 2023 is after"):
        await mcp_call(
            server, "usda_psd_get_time_series", {**arguments, "start_year": 2023, "end_year": 2021}
        )


def test_time_series_of_two_attributes_by_year_then_upstream_order(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    """The ids may come in any order: each year's records keep upstream's order (Production
    before Exports), and ``meta.request`` keeps the list as given."""
    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    ids = [AttributeId.EXPORTS, AttributeId.PRODUCTION]
    result = tasks.get_time_series(WHEAT, "US", 2021, 2023, attribute_id=ids)
    assert len(respx_mock.calls) == 3
    assert [(r.market_year, r.attribute_id) for r in result.data] == [
        (2021, 28),
        (2021, 88),
        (2022, 28),
        (2022, 88),
        (2023, 28),
        (2023, 88),
    ]
    expected = [
        record
        for year in (2021, 2022, 2023)
        for record in _recorded(DATA, f"wheat_us_{year}", list[CommodityData])
        if record.attribute_id in (28, 88)
    ]
    assert result.data == expected, "records exactly as upstream sent them"
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "country_code": "US",
        "start_year": 2021,
        "end_year": 2023,
        "attribute_id": [88, 28],
    }
    assert result.meta.vintage == "2026-07"


def test_time_series_without_attribute_id_keeps_every_record(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Omitted, ``attribute_id`` keeps every attribute: each year's whole answer, in
    order, and ``meta.request`` leaves the parameter out (conventions §4)."""
    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    result = tasks.get_time_series(WHEAT, "US", 2021, 2023)
    expected = [
        record
        for year in (2021, 2022, 2023)
        for record in _recorded(DATA, f"wheat_us_{year}", list[CommodityData])
    ]
    assert result.data == expected
    assert [r.market_year for r in result.data] == [2021] * 15 + [2022] * 15 + [2023] * 15
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "country_code": "US",
        "start_year": 2021,
        "end_year": 2023,
    }
    assert result.meta.vintage == "2026-07"


def test_time_series_checks_every_attribute_id_before_any_request(
    respx_mock: respx.MockRouter,
) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    with pytest.raises(UnknownCode, match="999 is not an attribute_id") as unknown:
        tasks.get_time_series(WHEAT, "US", 2021, 2023, attribute_id=[28, 999])
    assert unknown.value.closest == (("99", "Refined Exp.(Raw Val)"),)
    with pytest.raises(InvalidRequestError, match="attribute_id must name at least one id"):
        tasks.get_time_series(WHEAT, "US", 2021, 2023, attribute_id=[])
    with pytest.raises(InvalidRequestError, match="attribute_id must be an integer"):
        tasks.get_time_series(WHEAT, "US", 2021, 2023, attribute_id=[28, True])
    with pytest.raises(InvalidRequestError, match="attribute_id must be an integer"):
        tasks.get_time_series(WHEAT, "US", 2021, 2023, attribute_id="28")  # type: ignore[arg-type]
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_time_series_of_several_attributes_through_both_adapters(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """A list of ids is a keyword argument of the tool; since ``attribute_id`` takes a list,
    the HTTP route is a ``POST`` with a JSON body (conventions §9, sdk-core ADR-0007). A value the
    tool's schema refuses comes back as core's ``InvalidRequestError`` text."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.psd.http import router

    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    arguments: dict[str, Any] = {
        "commodity_code": WHEAT,
        "country_code": "US",
        "start_year": 2021,
        "end_year": 2023,
        "attribute_id": [28, 88],
    }
    payload = await mcp_call(server, "usda_psd_get_time_series", arguments)
    assert [(row["market_year"], row["attribute_id"]) for row in payload["data"]] == [
        (2021, 28),
        (2021, 88),
        (2022, 28),
        (2022, 88),
        (2023, 28),
        (2023, 88),
    ]
    assert payload["meta"]["request"] == arguments
    refused = await mcp_call_text(
        server, "usda_psd_get_time_series", {**arguments, "attribute_id": ["Production"]}
    )
    assert refused.startswith("error: InvalidRequestError: attribute_id")
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post("/usda-psd/get_time_series", json=arguments)
    assert response.status_code == 200, response.text
    assert [row["value"] for row in response.json()["data"]][:2] == [44804.0, 21656.0]


@pytest.mark.anyio
async def test_a_cut_series_names_the_filters_that_narrow_it(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The tool's own note (conventions §8, sdk-core ADR-0038) on a server built for this test with
    the package's cap for ``get_time_series``, its rows lowered to 20 so that three
    recorded years of every attribute, 45 records, are cut. The real cap is 200 rows."""
    from xippios.core.mcp import ToolSet, build_server

    cap = tasks.MCP_CAPS["get_time_series"]
    assert (cap.max_rows, cap.max_bytes) == (200, 65536)
    lowered = build_server(
        ToolSet(
            "usda-psd",
            [tasks.get_time_series],
            caps={"get_time_series": dataclasses.replace(cap, max_rows=20)},
        )
    )
    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    payload = await mcp_call(
        lowered,
        "usda_psd_get_time_series",
        {"commodity_code": WHEAT, "country_code": "US", "start_year": 2021, "end_year": 2023},
    )
    assert len(payload["data"]) == 20
    assert payload["note"] == (
        "showing 20 of 45 rows (cap: 20 rows or 65536 bytes); filter by attribute_id or "
        "narrow start_year and end_year to see the rest"
    )


def test_the_series_checks_its_arguments_before_any_request(respx_mock: respx.MockRouter) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    with pytest.raises(UnknownCode, match="999 is not an attribute_id") as unknown:
        tasks.get_time_series(WHEAT, "US", 2021, 2023, 999)
    assert unknown.value.closest == (("99", "Refined Exp.(Raw Val)"),)
    with pytest.raises(InvalidRequestError, match="attribute_id must be an integer"):
        tasks.get_time_series(WHEAT, "US", 2021, 2023, True)
    with pytest.raises(InvalidRequestError, match="start_year 2023 is after end_year 2021"):
        tasks.get_time_series(WHEAT, "US", 2023, 2021, 28)
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_time_series(WHEAT, "US", 21, 2023, 28)
    with pytest.raises(InvalidRequestError, match="start_year must be 1960 or later") as early:
        tasks.get_time_series(WHEAT, "US", 1959, 2023, 28)
    assert "PSD Database has data for most commodities since year 1960" in str(early.value)
    with pytest.raises(InvalidRequestError, match="start_year must be 1960 or later"):
        tasks.get_time_series(WHEAT, "US", 1900, 1900, 28)
    with pytest.raises(InvalidRequestError, match="1960 to 2060 is 101 market years"):
        tasks.get_time_series(WHEAT, "US", 1960, 2060, 28)
    with pytest.raises(InvalidRequestError, match="spans at most 100"):
        tasks.get_time_series(WHEAT, "US", 1960, 9999, 28)
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_time_series(WHEAT, "US", 2021, 20230, 28)
    with pytest.raises(UnknownCode, match="'XX' is not a country_code"):
        tasks.get_time_series(WHEAT, "XX", 2021, 2023, 28)
    assert not respx_mock.calls
