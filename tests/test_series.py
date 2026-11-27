"""The time series: one country's records of a commodity over a range of market years.

Each test replays recorded answers and checks that the series puts together and orders
upstream's records without changing one (sdk-core ADR-0028). ``_recorded`` parses a fixture the
way the wrapper does, without a call, so a test can compare with what upstream sent while
still counting the task's own requests.
"""

import argparse
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
    result = tasks.get_time_series(
        WHEAT, "US", start_year=2021, end_year=2023, attribute_id=AttributeId.PRODUCTION
    )
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
    assert result.meta.names == {
        "commodity_code": {WHEAT: "Wheat"},
        "country_code": {"US": "United States"},
        "attribute_id": {"28": "Production"},
        "unit_id": {"8": "(1000 MT)"},
    }, "the codes asked for and those of the rows"
    assert result.meta.notes == [
        "Market years in the order of the rows: 2021 with 1 row, 2022 with 1 row, 2023 with 1 row."
    ]


def test_time_series_leaves_a_year_without_data_out(
    replay_fixture: ReplayFixture,
    respx_mock: respx.MockRouter,
) -> None:
    """2022 answers PSD's 404 for a year without data: the recorded 1900 answer (empty
    body, ``text/plain``), NOT RECORDED at the 2022 path (conventions §10, kind 3), a state
    PSD answers alike at any market year it holds no data for, within one operation. The year
    is passed over, nothing filled."""
    absent = load_fixture(fixture_path(FIXTURES, DATA, "unknown_year"))
    assert (absent.response.status, absent.response.content) == (404, b""), "PSD's empty 404"
    replay_fixture(DATA, "wheat_us_2021")
    replay_fixture(DATA, "wheat_us_2023")
    missing = replay_fixture(DATA, "unknown_year", url=f"https://api.fas.usda.gov{_path(2022)}")
    result = tasks.get_time_series(
        WHEAT, "US", start_year=2021, end_year=2023, attribute_id=AttributeId.EXPORTS
    )
    assert missing.call_count == 1
    assert len(respx_mock.calls) == 3
    assert [(r.market_year, r.value) for r in result.data] == [
        (2021, Decimal("21656.0")),
        (2023, Decimal("19212.0")),
    ]
    assert result.meta.vintage == "2026-07"
    assert result.meta.notes == [
        "Market years in the order of the rows: 2021 with 1 row, 2023 with 1 row; passed over, "
        "without data in PSD: 2022."
    ], "https://github.com/xippios/sdk-usda-psd/issues/26"


def test_a_series_without_any_record_is_empty_not_an_error(replay_fixture: ReplayFixture) -> None:
    """The recorded empty 404 for 1900, NOT RECORDED at the 1960 path (conventions §10, kind
    3), a state PSD answers alike at any market year it holds no data for, within one
    operation: the first year a series may ask for is accepted, it is passed over, and the
    series is a valid empty list."""
    absent = load_fixture(fixture_path(FIXTURES, DATA, "unknown_year"))
    assert (absent.response.status, absent.response.content) == (404, b""), "PSD's empty 404"
    route = replay_fixture(DATA, "unknown_year", url=f"https://api.fas.usda.gov{_path(1960)}")
    result = tasks.get_time_series(
        WHEAT, "US", start_year=1960, end_year=1960, attribute_id=AttributeId.PRODUCTION
    )
    assert result.data == []
    assert (result.meta.vintage, result.meta.published_at) == (None, None)
    assert result.meta.notes == ["Market years passed over, without data in PSD: 1960."]
    assert route.call_count == 1


def test_the_gateways_not_found_inside_a_series_is_raised(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    """NOT RECORDED: api.data.gov's documented ``NOT_FOUND`` body at the 2022 path, composed in the
    shape the gateway documents (conventions §10, kind 2). It says the request is wrong, not
    that the year is empty, so the series stops there instead of passing the year over,
    names the market years answered before it and returns nothing (core's ``fetch_periods``;
    https://github.com/xippios/sdk-usda-psd/issues/32)."""
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
        tasks.get_time_series(
            WHEAT, "US", start_year=2021, end_year=2023, attribute_id=AttributeId.PRODUCTION
        )
    assert not isinstance(info.value, NoDataForYear)
    assert f"api.data.gov has no route for GET {_path(2022)}" in str(info.value)
    assert str(info.value).endswith(
        "The series stopped at 2022 after 1 period answered, 2021, and returns nothing."
    )
    assert gateway.call_count == 1
    assert later.call_count == 0, "nothing after the error is requested"


def test_a_series_may_span_exactly_the_ceiling(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    """The ceiling counts market years, ends included: set to 3 for the process, 2021 to 2023
    is asked for and 2021 to 2024 refused before any request, in core's words. The ceiling is
    100 in Python and over HTTP, core's ``Ceiling`` (the maintainer's decision of 2026-11-26)."""
    assert (tasks.SERIES.most, tasks.SERIES.value, tasks.SERIES.unit) == (100, 100, "market years")
    tasks.SERIES.set(3)
    try:
        with pytest.raises(InvalidRequestError) as refused:
            tasks.get_time_series(
                WHEAT, "US", start_year=2021, end_year=2024, attribute_id=AttributeId.PRODUCTION
            )
        assert not respx_mock.calls
        for year in (2021, 2022, 2023):
            replay_fixture(DATA, f"wheat_us_{year}")
        result = tasks.get_time_series(
            WHEAT, "US", start_year=2021, end_year=2023, attribute_id=AttributeId.PRODUCTION
        )
    finally:
        tasks.SERIES.set(100)
    assert str(refused.value).startswith(
        "2021 to 2024 is 4 market years; one call fetches at most 3 market years, the ceiling "
        "set for this process (the MCP server starts with 24 by default; --series-years "
        "raises it, up to 100). Nothing was sent."
    )
    assert [r.market_year for r in result.data] == [2021, 2022, 2023]


def test_the_mcp_server_starts_with_a_ceiling_of_24_market_years(
    respx_mock: respx.MockRouter,
) -> None:
    """A host that applies the tool set's hooks with their defaults serves the ceiling that
    the entry point serves, 24 market years, and a range of 25 is refused before any request,
    naming the ceiling and the option that raises it (sdk-core ADR-0054)."""
    from xippios.usda.psd.mcp import build

    tools = build()
    assert tools.apply_options is not None
    tools.apply_options(tools.option_defaults())
    try:
        assert tasks.SERIES.value == 24
        with pytest.raises(InvalidRequestError) as refused:
            tasks.get_time_series(WHEAT, "US", start_year=2000, end_year=2024)
    finally:
        tasks.SERIES.set(100)
    assert "2000 to 2024 is 25 market years; one call fetches at most 24 market years" in str(
        refused.value
    )
    assert "--series-years raises it, up to 100). Nothing was sent." in str(refused.value)
    assert not respx_mock.calls


@pytest.mark.parametrize(("argv", "value"), [([], 24), (["--series-years", "60"], 60)])
def test_the_entry_point_applies_series_years(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], value: int
) -> None:
    """``--series-years`` sets the server's ceiling from 1 to 100, 24 by default; the server's
    ``run`` is patched on its class, so nothing is served."""
    from mcp.server.mcpserver import MCPServer
    from xippios.core.mcp import main

    from xippios.usda.psd.mcp import build

    served: list[object] = []
    monkeypatch.setattr(MCPServer, "run", lambda self, **kwargs: served.append(kwargs))
    try:
        main(build, argv=argv)
        assert tasks.SERIES.value == value
    finally:
        tasks.SERIES.set(100)
    assert served == [{"transport": "stdio"}]


@pytest.mark.parametrize("given", ["0", "101"])
def test_the_entry_point_refuses_a_ceiling_outside_1_to_100(
    capsys: pytest.CaptureFixture[str], given: str
) -> None:
    from xippios.core.mcp import main

    from xippios.usda.psd.mcp import build

    with pytest.raises(SystemExit) as stopped:
        main(build, argv=["--series-years", given])
    assert stopped.value.code == 2
    assert (
        f"the series ceiling, --series-years on the MCP server, must be a whole number of "
        f"market years from 1 to 100, got {given}." in capsys.readouterr().err
    )
    assert tasks.SERIES.value == 100


def test_the_description_states_the_most_that_one_call_sends() -> None:
    """Conventions §8 and sdk-core ADR-0061, decision 8: 100 requests in Python and over
    HTTP, 24 over MCP, each with core's four attempts."""
    description = (tasks.get_time_series.__doc__ or "").split("Args:")[0]
    assert "at most 100 requests, 400" in description
    assert "attempts with retries, and 24 and 96 over MCP" in description
    assert len(description.strip()) < 1000


@pytest.mark.anyio
async def test_the_arguments_say_what_an_unreleased_year_answers_and_where_the_filter_runs() -> (
    None
):
    """Conventions §4: a series' docstring says what a period that upstream has not released
    answers; conventions §2 (sdk-core ADR-0061, decision 2): a filter after the fetch is said
    in its task's docstring. Both stand under ``Args:``, so the tool's input schema carries
    them and the description before it keeps its bound."""
    tools = {tool.name: tool for tool in await server.list_tools()}
    properties = tools["usda_psd_get_time_series"].input_schema["properties"]
    end_year = " ".join(properties["end_year"]["description"].split())
    attribute_id = " ".join(properties["attribute_id"]["description"].split())
    assert (
        "A market year PSD has not released is expected to answer its empty 404, as 1900 does "
        "(an unreleased year is not recorded), and is passed over in ``meta.notes``, still "
        "costing its request."
    ) in end_year
    assert (
        "PSD's data operations take no attribute, so the package keeps the records of the ids "
        "asked for after each fetch."
    ) in attribute_id


def test_the_option_hooks_are_the_ceilings() -> None:
    parser = argparse.ArgumentParser()
    tasks.mcp_add_options(parser)
    assert parser.parse_args([]).series_years == 24
    assert tasks.mcp_add_options == tasks.SERIES.add_options
    assert tasks.mcp_apply_options == tasks.SERIES.apply_options


def test_a_series_of_an_attribute_the_answers_lack_is_empty(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    """Area Planted (1) is a packaged attribute that wheat US does not report."""
    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    result = tasks.get_time_series(
        WHEAT, "US", start_year=2021, end_year=2023, attribute_id=AttributeId.AREA_PLANTED
    )
    assert result.data == []
    assert result.meta.vintage is None
    assert result.meta.notes == [
        "Market years passed over, answered without a record of the attributes asked for: "
        "2021, 2022, 2023."
    ]
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
    result = tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023, attribute_id=ids)
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
    result = tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023)
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
        tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023, attribute_id=[28, 999])
    assert unknown.value.closest == ((99, "Refined Exp.(Raw Val)"),)
    with pytest.raises(InvalidRequestError, match="attribute_id lists no code") as empty:
        tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023, attribute_id=[])
    assert "Nothing was sent." in empty.value.message
    with pytest.raises(InvalidRequestError, match="True is not an integer code"):
        tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023, attribute_id=[28, True])
    with pytest.raises(InvalidRequestError, match="Pass it as the integer 28"):
        tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023, attribute_id="28")  # type: ignore[arg-type]
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_time_series_of_several_attributes_through_both_adapters(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """A list of ids is a keyword argument of the tool; since ``attribute_id`` takes a list,
    the HTTP route is a ``POST`` with a JSON body (conventions §9, sdk-core ADR-0007)."""
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
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post("/usda-psd/get_time_series", json=arguments)
    assert response.status_code == 200, response.text
    assert [row["value"] for row in response.json()["data"]][:2] == [44804.0, 21656.0]


@pytest.mark.anyio
async def test_a_cut_series_names_the_filters_that_narrow_it(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The tool's own note (conventions §8, sdk-core ADR-0038) on a server built for this test
    with the package's cap for ``get_time_series``, its rows lowered to 20 so that three
    recorded years of every attribute, 45 records, are cut: the newest rows are shown, oldest
    first (sdk-core ADR-0047). The real cap is 200 rows."""
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
    every = tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023).data
    assert payload["data"] == [row.model_dump(mode="json") for row in every[-20:]], "the newest"
    assert payload["note"].startswith("showing rows 26 to 45 of 45 (cap: 20 rows or 65536 bytes)")
    assert payload["note"].endswith(
        "the newest market years are shown; pass attribute_id or narrow start_year and "
        "end_year to see the rest. One call sends one request per market year, at most 24 "
        "requests and 96 attempts with retries unless --series-years sets another ceiling"
    )


def test_the_series_checks_its_arguments_before_any_request(respx_mock: respx.MockRouter) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    with pytest.raises(UnknownCode, match="999 is not an attribute_id") as unknown:
        tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023, attribute_id=999)
    assert unknown.value.closest == ((99, "Refined Exp.(Raw Val)"),)
    with pytest.raises(InvalidRequestError, match="True is not an integer code"):
        tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=2023, attribute_id=True)
    with pytest.raises(
        InvalidRequestError, match=r"start_year 2023 is after end_year 2021\. Nothing was sent\."
    ):
        tasks.get_time_series(WHEAT, "US", start_year=2023, end_year=2021, attribute_id=28)
    with pytest.raises(InvalidRequestError, match="start_year must be a four-digit year"):
        tasks.get_time_series(WHEAT, "US", start_year=21, end_year=2023, attribute_id=28)
    with pytest.raises(InvalidRequestError, match="start_year must be 1960 or later") as early:
        tasks.get_time_series(WHEAT, "US", start_year=1959, end_year=2023, attribute_id=28)
    assert "got 1959. Nothing was sent." in str(early.value)
    assert "PSD Database has data for most commodities since year 1960" in str(early.value)
    with pytest.raises(InvalidRequestError, match="start_year must be 1960 or later"):
        tasks.get_time_series(WHEAT, "US", start_year=1900, end_year=1900, attribute_id=28)
    with pytest.raises(InvalidRequestError, match="1960 to 2060 is 101 market years"):
        tasks.get_time_series(WHEAT, "US", start_year=1960, end_year=2060, attribute_id=28)
    with pytest.raises(InvalidRequestError, match="one call fetches at most 100 market years"):
        tasks.get_time_series(WHEAT, "US", start_year=1960, end_year=9999, attribute_id=28)
    with pytest.raises(InvalidRequestError, match="end_year must be a four-digit year"):
        tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=20230, attribute_id=28)
    with pytest.raises(UnknownCode, match="'XX' is not a country_code"):
        tasks.get_time_series(WHEAT, "XX", start_year=2021, end_year=2023, attribute_id=28)
    assert not respx_mock.calls
