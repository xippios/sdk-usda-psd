"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.
"""

import inspect
import re
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
import respx
from xippios.core import InvalidRequestError, NotFoundError, ResultCap, UnknownCode
from xippios.core.mcp import ToolSet
from xippios.core.testing import mcp_call, mcp_call_text
from xippios.usda.fas import NoDataForYear

from xippios.usda.psd import __version__, tasks
from xippios.usda.psd import mcp as psd_mcp
from xippios.usda.psd._client import BASE_URL
from xippios.usda.psd.enums import AttributeId, UnitId
from xippios.usda.psd.mcp import server

WHEAT, CORN, SOYBEANS = "0410000", "0440000", "2222000"
DATA = "get_country_commodity_data_by_year"
ALL = "get_commodity_data_by_year"
WORLD = "get_world_commodity_data_by_year"
RELEASES = "get_data_release_info"
WORLD_HINT = "use get_world_data (over MCP, the tool usda_psd_get_world_data) for world data"
"""How a refusal names the task to call instead and its tool (conventions §8)."""


def no_data(path: str) -> str:
    """The note of the empty answer for PSD's empty 404 at ``path``."""
    return (
        f"PSD answered GET {path} with HTTP 404 and an empty body, its answer for a market year "
        "it holds no data for, which a market year it has not released is expected to answer "
        "alike; get_release_dates names the market years that hold data."
    )


def test_get_data_for_one_country(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    data = replay_fixture(DATA, "wheat_us_2023")
    result = tasks.get_data(WHEAT, 2023, country_code="US")
    assert data.call_count == 1, "one call: vintage comes from the records"
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
    assert result.meta.vintage == "2026-07"
    assert result.meta.published_at is None
    assert data.calls.last.request.headers["Accept"] == "application/json"
    names = result.meta.names
    assert set(names) == {"commodity_code", "country_code", "attribute_id", "unit_id"}
    assert (names["commodity_code"], names["country_code"]) == (
        {WHEAT: "Wheat"},
        {"US": "United States"},
    )
    assert names["attribute_id"]["28"] == "Production"
    assert len(names["attribute_id"]) == 15, "every attribute of the rows"
    assert names["unit_id"]["8"] == "(1000 MT)", "upstream's padding collapsed"
    assert result.meta.notes == [], "every code of the rows is in its packaged list"


def test_get_data_for_every_country(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    """``country/all``: records carry different releases; ``vintage`` is the latest. The
    fixture is cut (sdk-core ADR-0040, decision 5), so the shape is checked, not the count."""
    route = replay_fixture(ALL, "wheat_all_2023")
    result = tasks.get_data(WHEAT, 2023)
    assert route.call_count == 1
    assert result.meta.endpoint == "PSDData_GetCommodityDataByYear"
    assert result.meta.request == {"commodity_code": WHEAT, "market_year": 2023}
    assert {r.market_year for r in result.data} == {2023}
    assert len({r.country_code for r in result.data}) > 1
    assert len({(r.calendar_year, r.month) for r in result.data}) > 1
    assert result.meta.vintage == "2026-10"
    assert result.meta.published_at is None
    assert set(result.meta.names["country_code"]) == {r.country_code for r in result.data}
    assert result.meta.names["country_code"]["AR"] == "Argentina"


def test_get_world_data(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    world = replay_fixture(WORLD, "wheat_world_2023")
    result = tasks.get_world_data(WHEAT, 2023)
    assert world.call_count == 1
    assert result.meta.endpoint == "PSDData_GetWorldCommodityDataByYear"
    assert result.meta.request == {"commodity_code": WHEAT, "market_year": 2023}
    assert len(result.data) == 15
    assert {r.country_code for r in result.data} == {"00"}
    assert {(r.calendar_year, r.month) for r in result.data} == {(2026, 10)}
    assert result.meta.vintage == "2026-10"
    assert result.meta.published_at is None
    assert "country_code" not in result.meta.names, "the world's 00 is no packaged country"
    assert result.meta.names["commodity_code"] == {WHEAT: "Wheat"}
    assert result.meta.notes == [
        "The packaged countries list (fetched 2026-10-28) holds no name for country_code 00 "
        "of this answer, so meta.names leaves it out."
    ]


def test_vintage_is_none_for_an_empty_answer() -> None:
    assert tasks._vintage([]) is None


def test_get_release_dates(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    route = replay_fixture(RELEASES, "wheat")
    result = tasks.get_release_dates(WHEAT)
    assert result.data
    assert {r.commodity_code for r in result.data} == {WHEAT}
    assert result.meta.endpoint == "PSDData_GetDataReleaseInfo"
    assert result.meta.request == {"commodity_code": WHEAT}, "filters left None are left out"
    assert result.meta.published_at is None
    assert result.meta.vintage == "2024-02", "the newest release of the cut list, Pakistan's"
    assert route.call_count == 1
    assert result.meta.names["commodity_code"] == {WHEAT: "Wheat"}
    assert set(result.meta.names["country_code"]) == {r.country_code for r in result.data}


def test_release_dates_vintage_is_the_newest_release_of_the_whole_list(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """``meta.vintage`` of ``get_release_dates`` is the newest release of upstream's whole
    list, ``"YYYY-MM"`` as the data tasks write it, also where the filters or ``since`` keep
    none of it, so a stored vintage polls for a newer release with one request (conventions
    §4: the newest where an answer holds several, that of the whole upstream answer)."""
    route = replay_fixture(RELEASES, "wheat")
    every = tasks.get_release_dates(WHEAT)
    newest = max((r.release_year, r.release_month) for r in every.data)
    assert every.meta.vintage == f"{newest[0]:04d}-{newest[1]:02d}" == "2024-02"
    one = tasks.get_release_dates(WHEAT, market_year=1960, country_code="US")
    assert [(r.release_year, r.release_month) for r in one.data] == [(2006, 7)]
    assert one.meta.vintage == "2024-02", "the whole list's, not the record's"
    polled = tasks.get_release_dates(WHEAT, since=every.meta.vintage)
    assert polled.data == []
    assert polled.meta.vintage == "2024-02", "nothing newer, and the marker to store again"
    assert route.call_count == 1


@pytest.mark.anyio
async def test_the_release_list_tool_carries_its_vintage(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture(RELEASES, "wheat")
    payload = await mcp_call(
        server, "usda_psd_get_release_dates", {"commodity_code": WHEAT, "since": "2024-02"}
    )
    assert payload["data"] == []
    assert payload["meta"]["vintage"] == "2024-02"


def test_get_release_dates_filters_after_the_one_call(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The cut list holds market years 1960 to 1978 (upstream orders it by market year), so
    the filters are checked on 1975 and against the unfiltered answer."""
    route = replay_fixture(RELEASES, "wheat")
    every = tasks.get_release_dates(WHEAT).data
    one = tasks.get_release_dates(WHEAT, market_year=1975, country_code="US")
    assert [(r.country_code, r.market_year, r.release_year, r.release_month) for r in one.data] == [
        ("US", 1975, 2006, 7)
    ]
    assert one.meta.request == {"commodity_code": WHEAT, "market_year": 1975, "country_code": "US"}
    year = tasks.get_release_dates(WHEAT, market_year=1975)
    assert year.data == [r for r in every if r.market_year == 1975]
    assert len({r.country_code for r in year.data}) == len(year.data), "one per country"
    country = tasks.get_release_dates(WHEAT, country_code="US")
    assert country.data == [r for r in every if r.country_code == "US"]
    assert len({r.market_year for r in country.data}) == len(country.data), "one per market year"
    assert route.call_count == 1, "core's cache answers the three calls after the first"


def test_get_release_dates_since_keeps_later_releases_only(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Strictly after ``since``: the cut list's two newest releases are 2022-09 (Syria's
    revision of 1960 to 1977) and 2024-02 (Pakistan's)."""
    route = replay_fixture(RELEASES, "wheat")
    every = tasks.get_release_dates(WHEAT).data
    later = tasks.get_release_dates(WHEAT, since="2022-08")
    assert later.data == [r for r in every if (r.release_year, r.release_month) > (2022, 8)]
    assert {(r.country_code, r.release_year, r.release_month) for r in later.data} == {
        ("SY", 2022, 9),
        ("PK", 2024, 2),
    }
    strictly = tasks.get_release_dates(WHEAT, since="2022-09")
    assert {(r.country_code, r.release_year, r.release_month) for r in strictly.data} == {
        ("PK", 2024, 2)
    }, "the release since names is not kept"
    assert strictly.meta.request == {"commodity_code": WHEAT, "since": "2022-09"}
    one_year = tasks.get_release_dates(WHEAT, market_year=1975, since="2022-08")
    assert [(r.country_code, r.market_year) for r in one_year.data] == [("PK", 1975), ("SY", 1975)]
    assert one_year.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 1975,
        "since": "2022-08",
    }
    assert tasks.get_release_dates(WHEAT, since="2024-02").data == []
    assert route.call_count == 1, "core's cache answers the four calls after the first"


@pytest.mark.anyio
async def test_release_dates_since_through_the_tool(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture(RELEASES, "wheat")
    payload = await mcp_call(
        server,
        "usda_psd_get_release_dates",
        {"commodity_code": WHEAT, "country_code": "PK", "since": "2022-09"},
    )
    assert {(row["release_year"], row["release_month"]) for row in payload["data"]} == {(2024, 2)}
    assert "note" not in payload
    assert payload["meta"]["request"] == {
        "commodity_code": WHEAT,
        "country_code": "PK",
        "since": "2022-09",
    }
    with pytest.raises(AssertionError, match="InvalidRequestError: since must be a PSD release"):
        await mcp_call(
            server, "usda_psd_get_release_dates", {"commodity_code": WHEAT, "since": "2026-13"}
        )


def test_the_cut_tools_keep_the_familys_limits_with_a_note_of_their_own() -> None:
    """``get_data``, ``get_release_dates`` and ``get_time_series`` keep 200 rows or 64 KB,
    ``ResultCap``'s defaults, and name their filters; ``list_countries`` has 300 rows;
    every other tool has no entry, so core's default cap and note apply to it (conventions
    §8, sdk-core ADR-0038). The two tools of one request each are paged, since core's cache
    answers a continuation (sdk-core ADR-0061, decision 9), and the series keeps its newest
    market years and states the most that one call sends on the MCP server."""
    default = ResultCap()
    assert (default.max_rows, default.max_bytes, default.note) == (200, 65536, None)
    noted = ("get_data", "get_release_dates", "get_time_series")
    for name in noted:
        cap = tasks.MCP_CAPS[name]
        assert (cap.max_rows, cap.max_bytes) == (default.max_rows, default.max_bytes), name
        assert cap.note is not None, name
    assert tasks.MCP_CAPS["get_data"].paged
    assert tasks.MCP_CAPS["get_release_dates"].paged
    series = tasks.MCP_CAPS["get_time_series"]
    assert (series.paged, series.keep) == (False, "last")
    assert series.note is not None
    assert "at most 24 requests and 96 attempts with retries" in series.note
    assert tasks.MCP_CAPS["list_countries"].max_rows == 300
    assert set(tasks.MCP_CAPS) == {"list_countries", *noted}
    assert set(tasks.MCP_CAPS) < set(tasks.__all__)


@pytest.mark.anyio
async def test_a_cut_release_list_continues_from_the_cache(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Wheat's release list over MCP, every country and market year: cut at 200 rows with a
    note naming the tool's own filters and the ``offset`` to continue with, and the second
    page is the cache's, so the list is sent once (sdk-core ADR-0038, ADR-0061, decision 9;
    https://github.com/xippios/sdk-usda-psd/issues/31)."""
    route = replay_fixture(RELEASES, "wheat")
    every = tasks.get_release_dates(WHEAT).data
    payload = await mcp_call(server, "usda_psd_get_release_dates", {"commodity_code": WHEAT})
    assert len(payload["data"]) == 200
    assert payload["note"] == (
        f"showing 200 of {len(every)} rows (cap: 200 rows or 65536 bytes); pass market_year, "
        "country_code or since to narrow the list; continue with offset=200"
    )
    second = await mcp_call(
        server, "usda_psd_get_release_dates", {"commodity_code": WHEAT, "offset": 200}
    )
    assert second["data"] == [row.model_dump(mode="json") for row in every[200:400]]
    assert route.call_count == 1, "the first call's answer, kept in core's cache"


@pytest.mark.anyio
async def test_a_cut_answer_for_every_country_names_country_code_and_continues(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(ALL, "wheat_all_2023")
    every = tasks.get_data(WHEAT, 2023).data
    arguments = {"commodity_code": WHEAT, "market_year": 2023}
    payload = await mcp_call(server, "usda_psd_get_data", arguments)
    assert len(payload["data"]) == 200
    assert payload["note"] == (
        f"showing 200 of {len(every)} rows (cap: 200 rows or 65536 bytes); pass country_code, "
        "e.g. US, for one country's rows; continue with offset=200"
    )
    second = await mcp_call(server, "usda_psd_get_data", {**arguments, "offset": 200})
    assert second["data"] == [row.model_dump(mode="json") for row in every[200:400]]
    assert route.call_count == 1, "the first call's answer, kept in core's cache"


def test_get_release_dates_validates_its_filters(respx_mock: respx.MockRouter) -> None:
    with pytest.raises(UnknownCode, match="Omit country_code"):
        tasks.get_release_dates(WHEAT, country_code="all")
    with pytest.raises(UnknownCode, match="the release list has no world record"):
        tasks.get_release_dates(WHEAT, country_code="00")
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_release_dates(WHEAT, market_year=23)
    for since in ("2026-13", "2026-00", "2026-9", "2026/09", "26-09", "2026-09-15", "", " 2026-09"):
        with pytest.raises(InvalidRequestError, match="since must be a PSD release month"):
            tasks.get_release_dates(WHEAT, since=since)
    with pytest.raises(InvalidRequestError, match="got 202609"):
        tasks.get_release_dates(WHEAT, since=202609)  # type: ignore[arg-type]
    assert not respx_mock.calls


def test_a_market_year_without_data_answers_the_empty_list_with_a_note(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Recorded: PSD's empty 404 for market year 1900. The list task answers the empty list
    with a note that names PSD's answer and points to ``get_release_dates``, and sends no
    second request (https://github.com/xippios/sdk-usda-esr/issues/88, the maintainer's
    decision of 2026-11-26)."""
    route = replay_fixture(DATA, "unknown_year")
    result = tasks.get_data(WHEAT, 1900, country_code="US")
    assert result.data == []
    assert result.meta.notes == [no_data("/api/psd/commodity/0410000/country/US/year/1900")]
    assert result.meta.endpoint == "PSDData_GetCountryCommodityDataByYear"
    assert (result.meta.vintage, result.meta.published_at) == (None, None)
    assert result.meta.names == {
        "commodity_code": {WHEAT: "Wheat"},
        "country_code": {"US": "United States"},
    }, "the codes asked for"
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 1900,
        "country_code": "US",
    }
    assert route.call_count == 1, "no second request"


def test_unknown_codes_are_refused_before_any_request(respx_mock: respx.MockRouter) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    with pytest.raises(UnknownCode, match="0410000 \\(Wheat\\)"):
        tasks.get_data("0410001", 2023, country_code="US")
    with pytest.raises(UnknownCode, match="'XX' is not a country_code"):
        tasks.get_data(WHEAT, 2023, country_code="XX")
    with pytest.raises(UnknownCode, match=re.escape(WORLD_HINT)) as world:
        tasks.get_data(WHEAT, 2023, country_code="00")
    assert world.value.closest == ()
    with pytest.raises(UnknownCode, match="Omit country_code for every country"):
        tasks.get_data(WHEAT, 2023, country_code="all")
    with pytest.raises(UnknownCode):
        tasks.get_world_data("9999999", 2023)
    with pytest.raises(UnknownCode):
        tasks.get_release_dates("wheat")
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_data(WHEAT, 23, country_code="US")
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_mcp_tool_call_end_to_end(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture(DATA, "wheat_us_2023")
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
    assert payload["meta"]["published_at"] is None
    assert payload["meta"]["vintage"] == "2026-07"
    with pytest.raises(AssertionError, match=r"UnknownCode.*0410000 \(Wheat\)"):
        await mcp_call(
            server, "usda_psd_get_data", {"commodity_code": "0410001", "market_year": 2023}
        )


@pytest.mark.anyio
async def test_value_is_a_json_number_through_both_adapters(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """``Decimal`` in Python, a JSON number on the wire, never a string (sdk-core ADR-0031,
    decision 1): a JSON integer where upstream sends no fractional digit, else a JSON float,
    as core reads the decimal's exponent (sdk-core ADR-0067, decision 10). PSD's recorded
    answers carry four fractional digits, ``222218.0000``, so their values stay floats."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.psd.http import router

    replay_fixture(WORLD, "wheat_world_2023")
    payload = await mcp_call(
        server, "usda_psd_get_world_data", {"commodity_code": WHEAT, "market_year": 2023}
    )
    values = [row["value"] for row in payload["data"]]
    assert values
    recorded = tasks.get_world_data(WHEAT, 2023).data
    exponents = [record.value.as_tuple().exponent for record in recorded]
    assert [type(value) for value in values] == [
        int if isinstance(exponent, int) and exponent >= 0 else float for exponent in exponents
    ]
    assert {type(value) for value in values} == {float}, "upstream sends fractional digits"
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


SIGNATURES = {
    "get_data": (["commodity_code", "market_year"], ["country_code"]),
    "get_world_data": (["commodity_code", "market_year"], []),
    "get_time_series": (
        ["commodity_code", "country_code"],
        ["start_year", "end_year", "attribute_id"],
    ),
    "get_release_dates": (["commodity_code"], ["market_year", "country_code", "since"]),
    "list_countries": ([], ["region_code", "search"]),
    "list_commodities": ([], ["search"]),
    "list_commodity_attributes": ([], ["search"]),
    "list_regions": ([], []),
    "list_units_of_measure": ([], []),
}
"""Each task's arguments that identify a record, positional in the order of upstream's path,
and its filters and arguments of the package's own, keyword-only
(https://github.com/xippios/sdk-usda-esr/issues/60, part 1)."""


@pytest.mark.parametrize("name", sorted(SIGNATURES))
def test_a_task_takes_what_identifies_a_record_by_position_and_the_rest_by_keyword(
    name: str,
) -> None:
    """The sync task and its async twin alike, so that one concept stands at one position in
    every task (sdk-core ADR-0061, decision 5)."""
    positional, keyword = SIGNATURES[name]
    for task in (getattr(tasks, name), getattr(tasks, f"{name}_async")):
        parameters = inspect.signature(task).parameters.values()
        assert [p.name for p in parameters if p.kind is p.POSITIONAL_OR_KEYWORD] == positional
        assert [p.name for p in parameters if p.kind is p.KEYWORD_ONLY] == keyword


def test_a_filter_by_position_is_refused_before_any_request(
    respx_mock: respx.MockRouter,
) -> None:
    """Python refuses a filter passed by position, as the tasks' signatures take them by
    keyword alone; respx has no route mounted, so nothing is sent."""
    calls: list[Callable[[], object]] = [
        lambda: tasks.get_data(WHEAT, 2023, "US"),  # type: ignore[call-arg]
        lambda: tasks.get_release_dates(WHEAT, 2023),  # type: ignore[call-arg]
        lambda: tasks.get_time_series(WHEAT, "US", 2021, 2023),  # type: ignore[call-arg]
        lambda: tasks.list_countries("R01"),  # type: ignore[call-arg]
        lambda: tasks.list_commodities("wheat"),  # type: ignore[call-arg]
        lambda: tasks.list_commodity_attributes("stocks"),  # type: ignore[call-arg]
    ]
    for call in calls:
        with pytest.raises(TypeError, match="positional argument"):
            call()
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_the_adapters_take_the_arguments_by_name_as_before(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Over MCP every argument is named, so the order changes nothing there."""
    replay_fixture(DATA, "wheat_us_2023")
    payload = await mcp_call(
        server,
        "usda_psd_get_data",
        {"country_code": "US", "market_year": 2023, "commodity_code": WHEAT},
    )
    assert len(payload["data"]) == 15


@pytest.mark.parametrize("value", [2023.5, 2023.0, "2023"])
def test_a_market_year_that_is_no_whole_number_is_refused_before_any_request(
    respx_mock: respx.MockRouter, value: object
) -> None:
    """A float or a text is no market year, so every task refuses it before any request with
    ``InvalidRequestError`` that names the argument and the value, where ``2023.5`` passed the
    range check and reached the path as ``/year/2023.5``
    (https://github.com/xippios/sdk-usda-psd/issues/27)."""
    calls: list[tuple[str, Callable[[], object]]] = [
        ("market_year", lambda: tasks.get_data(WHEAT, value)),  # type: ignore[arg-type]
        ("market_year", lambda: tasks.get_world_data(WHEAT, value)),  # type: ignore[arg-type]
        ("market_year", lambda: tasks.get_release_dates(WHEAT, market_year=value)),  # type: ignore[arg-type]
        ("start_year", lambda: tasks.get_time_series(WHEAT, "US", start_year=value, end_year=2023)),  # type: ignore[arg-type]
        ("end_year", lambda: tasks.get_time_series(WHEAT, "US", start_year=2021, end_year=value)),  # type: ignore[arg-type]
    ]
    for param, call in calls:
        with pytest.raises(InvalidRequestError) as refused:
            call()
        assert str(refused.value).startswith(
            f"{param} must be a four-digit year such as 2023, got {value!r}. Nothing was sent."
        ), str(refused.value)
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_the_adapters_refuse_a_fractional_market_year_before_any_request(
    respx_mock: respx.MockRouter,
) -> None:
    """Over MCP and HTTP the schema of ``market_year``, an integer, refuses ``2023.5`` before
    the task runs (https://github.com/xippios/sdk-usda-psd/issues/27)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.psd.http import router

    text = await mcp_call_text(
        server, "usda_psd_get_data", {"commodity_code": WHEAT, "market_year": 2023.5}
    )
    assert text.startswith("error: InvalidRequestError"), text
    app = FastAPI()
    app.include_router(router)
    refused = TestClient(app).get(
        "/usda-psd/get_data", params={"commodity_code": WHEAT, "market_year": "2023.5"}
    )
    assert refused.status_code == 422
    assert not respx_mock.calls


def test_the_package_serves_the_nine_tasks_the_boundary_keeps() -> None:
    """The ranking, the pivot and the pick of the newest release leave by the boundary of a
    source package (sdk-core ADR-0060), with the models and the list of groupings of their
    own: a caller reads the same records from ``get_data`` and ``get_release_dates``."""
    from xippios.usda.psd import models

    assert sorted(tasks.__all__) == [
        "get_data",
        "get_release_dates",
        "get_time_series",
        "get_world_data",
        "list_commodities",
        "list_commodity_attributes",
        "list_countries",
        "list_regions",
        "list_units_of_measure",
    ]
    for name in ("get_balance_sheet", "get_top_countries", "get_latest_release", "GROUPINGS"):
        assert not hasattr(tasks, name), name
    for name in ("BalanceSheet", "BalanceSheetEntry"):
        assert not hasattr(models, name), name


def test_build_returns_the_tool_set_the_entry_point_serves() -> None:
    """``mcp.build()`` carries what ``tasks.py`` declares for the server, its caps and its
    instructions, with the package's version (conventions §8; sdk-core ADR-0063, decision 7);
    the rest of the package contract is the family check's."""
    tools = psd_mcp.build()
    assert isinstance(tools, ToolSet)
    assert dict(tools.caps or {}) == dict(tasks.MCP_CAPS)
    assert (tools.instructions, tools.version) == (tasks.MCP_INSTRUCTIONS, __version__)


def test_meta_retrieved_at_is_the_time_of_the_answer(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """A task's ``meta.retrieved_at`` is the client's time of the answer it read (conventions
    §4): a second call within the cache's lifetime is answered by the cache and carries the
    time its entry was stored, the first call's."""
    route = replay_fixture(DATA, "wheat_us_2023")
    first = tasks.get_data(WHEAT, 2023, country_code="US")
    second = tasks.get_data(WHEAT, 2023, country_code="US")
    assert route.call_count == 1
    assert second.meta.retrieved_at == first.meta.retrieved_at
    assert second.data == first.data


def test_valid_codes_without_data_are_an_empty_result(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Recorded: wheat for Bermuda (BD; PSD's BM is Burma) in 2023 answers 200 with ``[]``.
    Empty means empty, not an error: no vintage, nothing else fetched."""
    route = replay_fixture(DATA, "no_data_valid_codes")
    result = tasks.get_data(WHEAT, 2023, country_code="BD")
    assert result.data == []
    assert (result.meta.vintage, result.meta.published_at) == (None, None)
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 2023,
        "country_code": "BD",
    }
    assert result.meta.names == {
        "commodity_code": {WHEAT: "Wheat"},
        "country_code": {"BD": "Bermuda"},
    }, "an answer without rows names what was asked for"
    assert route.call_count == 1


def test_a_market_year_without_data_answers_alike_for_every_country(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Recorded: ``country/all`` for 1900 answers 404 with an empty body, like one country."""
    route = replay_fixture(ALL, "year_1900")
    result = tasks.get_data(WHEAT, 1900)
    assert result.data == []
    assert result.meta.notes == [no_data("/api/psd/commodity/0410000/country/all/year/1900")]
    assert result.meta.endpoint == "PSDData_GetCommodityDataByYear"
    assert route.call_count == 1


def test_a_market_year_without_data_answers_alike_for_the_world(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Recorded: the world form for 1900 answers 404 with an empty body as well."""
    route = replay_fixture(WORLD, "year_1900")
    result = tasks.get_world_data(WHEAT, 1900)
    assert result.data == []
    assert result.meta.notes == [no_data("/api/psd/commodity/0410000/world/year/1900")]
    assert result.meta.endpoint == "PSDData_GetWorldCommodityDataByYear"
    assert result.meta.names == {"commodity_code": {WHEAT: "Wheat"}}
    assert route.call_count == 1


@pytest.mark.anyio
async def test_the_empty_answer_reaches_the_tool_with_its_note(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture(DATA, "unknown_year")
    payload = await mcp_call(
        server,
        "usda_psd_get_data",
        {"commodity_code": WHEAT, "market_year": 1900, "country_code": "US"},
    )
    assert payload["data"] == []
    assert payload["meta"]["notes"] == [no_data("/api/psd/commodity/0410000/country/US/year/1900")]


GATEWAY_NOT_FOUND = {
    "error": {
        "code": "NOT_FOUND",
        "message": "The requested URL was not found on this server.",
    }
}
"""NOT A RECORDING: api.data.gov's documented ``NOT_FOUND`` body, composed in the shape the
gateway documents and the shared package's tests hold (conventions §10, kind 2)."""


@pytest.mark.parametrize(
    ("path", "call"),
    [
        ("country/US/year/2023", lambda: tasks.get_data(WHEAT, 2023, country_code="US")),
        ("country/all/year/2023", lambda: tasks.get_data(WHEAT, 2023)),
        ("world/year/2023", lambda: tasks.get_world_data(WHEAT, 2023)),
    ],
    ids=["one_country", "every_country", "world"],
)
def test_the_gateways_not_found_propagates_unchanged(
    respx_mock: respx.MockRouter, path: str, call: Callable[[], object]
) -> None:
    """Only PSD's empty 404 means "no data for this market year"; the gateway's 404 says
    the route is wrong and reaches the caller as classify raised it. NOT RECORDED: the body is
    composed from api.data.gov's documented answer (conventions §10, kind 2)."""
    path = f"/api/psd/commodity/{WHEAT}/{path}"
    respx_mock.get(f"{BASE_URL}{path}").mock(
        return_value=httpx.Response(404, json=GATEWAY_NOT_FOUND)
    )
    with pytest.raises(NotFoundError) as info:
        call()
    assert not isinstance(info.value, NoDataForYear)
    assert str(info.value).startswith(f"api.data.gov has no route for GET {path}")
    assert "get_release_dates names" not in str(info.value)
