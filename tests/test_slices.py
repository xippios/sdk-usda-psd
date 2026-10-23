"""The wave 2 slices: balance sheet, time series, top countries, latest release.

Each replays recorded answers and checks that the slice selects, orders or pivots
upstream's records without changing one (ADR-0003). ``_recorded`` parses a fixture the
way the wrapper does, without a call, so a test can compare with what upstream sent
while still counting the task's own requests. The two pure helpers, the balance-sheet
pivot and the newest-release filter, are also tested on in-memory records: those are
function inputs, not fixture files.
"""

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from xippios.core import InvalidRequestError, NotFoundError, ValidationError, parse
from xippios.core.testing import assert_projection, fixture_path, load_fixture, mcp_call

from xippios.usda.psd import tasks
from xippios.usda.psd.enums import AttributeId, UnitId
from xippios.usda.psd.errors import NoDataForYear, UnknownCode
from xippios.usda.psd.mcp import server
from xippios.usda.psd.models import BalanceSheetEntry, CommodityData, DataReleaseInfo
from xippios.usda.psd.params import attribute_names

FIXTURES = Path(__file__).parent / "fixtures"
WHEAT, CORN, SOYBEANS = "0410000", "0440000", "2222000"
DATA = "PSDData_GetCountryCommodityDataByYear"
ALL = "PSDData_GetCommodityDataByYear"
RELEASES = "PSDData_GetDataReleaseInfo"
SLICES = ["get_balance_sheet", "get_time_series", "get_top_countries", "get_latest_release"]

WHEAT_US_2023_KEYS = [
    "Area Harvested",
    "Beginning Stocks",
    "Production",
    "Imports",
    "TY Imports",
    "TY Imp. from U.S.",
    "Total Supply",
    "Exports",
    "TY Exports",
    "Feed Dom. Consumption",
    "FSI Consumption",
    "Domestic Consumption",
    "Ending Stocks",
    "Total Distribution",
    "Yield",
]
"""The attribute names of ``wheat_us_2023``, in the order upstream sent the records."""


def _recorded[T](endpoint: str, case: str, kind: type[list[T]]) -> list[T]:
    """The recorded answer parsed as the wrapper parses it, without a request."""
    body = json.loads(load_fixture(fixture_path(FIXTURES, endpoint, case)).response.body)
    return parse(kind, body, source="usda-psd", endpoint=endpoint)


def _data(market_year: int, attribute_id: int, *, country_code: str = "US") -> CommodityData:
    """An in-memory record for the pure pivot; every field as a data record has it."""
    return CommodityData(
        commodity_code=WHEAT,
        country_code=country_code,
        market_year=market_year,
        calendar_year=2026,
        month=7,
        attribute_id=attribute_id,
        unit_id=8,
        value=Decimal("1.5"),
    )


def _path(market_year: int, country_code: str = "US", commodity_code: str = WHEAT) -> str:
    return f"/api/psd/commodity/{commodity_code}/country/{country_code}/year/{market_year}"


def _mount_recorded_404(respx_mock: respx.MockRouter, market_year: int) -> respx.Route:
    """Serve PSD's recorded empty 404 for wheat US 1900 (``unknown_year``: status 404,
    empty ``text/plain`` body) at the path of ``market_year``: a recorded answer moved,
    not a hand-written one, standing in for a year without data inside a range."""
    absent = load_fixture(fixture_path(FIXTURES, DATA, "unknown_year"))
    assert (absent.response.status, absent.response.content) == (404, b"")
    return respx_mock.get(f"https://api.fas.usda.gov{_path(market_year)}").mock(
        return_value=httpx.Response(
            absent.response.status,
            headers=absent.response.headers,
            content=absent.response.content,
        )
    )


def test_every_slice_is_exported_as_a_tool() -> None:
    import xippios.usda.psd as package

    for name in SLICES:
        assert name in tasks.__all__
        assert name in package.__all__
        assert getattr(package, name) is getattr(tasks, name)


@pytest.mark.anyio
async def test_slice_tool_names() -> None:
    names = {tool.name for tool in await server.list_tools()}
    assert {f"usda_psd_{name}" for name in SLICES} <= names


# get_balance_sheet


def test_get_balance_sheet_pivots_one_country_year_losslessly(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(DATA, "wheat_us_2023")
    result = tasks.get_balance_sheet(WHEAT, "US", 2023)
    assert route.call_count == 1
    sheet = result.data
    assert (sheet.commodity_code, sheet.country_code, sheet.market_year) == (WHEAT, "US", 2023)
    assert list(sheet.attributes) == WHEAT_US_2023_KEYS, "upstream order, packaged names"
    recorded = _recorded(DATA, "wheat_us_2023", list[CommodityData])
    assert len(recorded) == len(sheet.attributes) == 15, "every record once"
    for record, (name, entry) in zip(recorded, sheet.attributes.items(), strict=True):
        assert_projection(entry, record)
        assert (record.commodity_code, record.country_code, record.market_year) == (
            WHEAT,
            "US",
            2023,
        )
        assert attribute_names()[record.attribute_id] == name
    production = sheet.attributes["Production"]
    assert production == BalanceSheetEntry(
        attribute_id=AttributeId.PRODUCTION,
        unit_id=UnitId._1000_MT,
        value=Decimal("49095.0"),
        calendar_year=2026,
        month=7,
    )
    units = {entry.unit_id for entry in sheet.attributes.values()}
    assert units == {4, 8, 26}, "1000 HA, 1000 MT and MT/HA, each entry its own"
    assert sheet.attributes["Area Harvested"].unit_id == 4
    assert sheet.attributes["Yield"].value == Decimal("3.2719")
    assert result.meta.source == "usda-psd"
    assert result.meta.endpoint == DATA
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "country_code": "US",
        "market_year": 2023,
    }
    assert result.meta.vintage == "2026-07"
    assert result.meta.published_at is None


def test_balance_sheet_keys_repeated_names_and_unknown_ids_by_id() -> None:
    """Pure pivot on in-memory records: "Total Disappearance" is 126 and 173, "Fresh Dom.
    Consumption" 133 and 135 in the packaged list; those ids always carry the id, an id
    the packaged list lacks is "attribute <id>"."""
    ids = [28, 126, 173, 133, 135, 9999, 176]
    sheet = tasks._balance_sheet([_data(2023, attribute_id) for attribute_id in ids])
    assert list(sheet.attributes) == [
        "Production",
        "Total Disappearance (126)",
        "Total Disappearance (173)",
        "Fresh Dom. Consumption (133)",
        "Fresh Dom. Consumption (135)",
        "attribute 9999",
        "Ending Stocks",
    ]
    assert [entry.attribute_id for entry in sheet.attributes.values()] == ids
    alone = tasks._balance_sheet([_data(2023, 126), _data(2023, 28), _data(2023, 135)])
    assert list(alone.attributes) == [
        "Total Disappearance (126)",
        "Production",
        "Fresh Dom. Consumption (135)",
    ], "the suffix follows the packaged list, not the answer: one key per id everywhere"


def test_every_packaged_attribute_gets_its_own_key() -> None:
    """All 85 packaged ids in one answer: 85 distinct keys, exactly the four ids of the two
    repeated names suffixed, and each id keyed as it is when it comes alone."""
    names = attribute_names()
    sheet = tasks._balance_sheet([_data(2023, attribute_id) for attribute_id in names])
    assert len(sheet.attributes) == len(names) == 85
    suffixed = {
        entry.attribute_id: key
        for key, entry in sheet.attributes.items()
        if key not in names.values()
    }
    assert suffixed == {
        126: "Total Disappearance (126)",
        133: "Fresh Dom. Consumption (133)",
        135: "Fresh Dom. Consumption (135)",
        173: "Total Disappearance (173)",
    }
    for key, entry in sheet.attributes.items():
        alone = tasks._balance_sheet([_data(2023, entry.attribute_id)])
        assert list(alone.attributes) == [key], entry.attribute_id


def test_balance_sheet_refuses_what_one_entry_per_record_cannot_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match=r"repeats attribute ids \[28\]"):
        tasks._balance_sheet([_data(2023, 28), _data(2023, 28)])
    with pytest.raises(ValidationError, match="also holds"):
        tasks._balance_sheet([_data(2023, 28), _data(2023, 88, country_code="BR")])
    with pytest.raises(ValidationError, match="also holds"):
        tasks._balance_sheet([_data(2023, 28), _data(2022, 88)])
    # A true collision, two records with the same final key: a future list where a plain
    # name equals another id's suffixed key ("A (2)" is 1, "A" is 2 and 3). Refused, not
    # merged.
    monkeypatch.setattr(tasks, "attribute_names", lambda: {1: "A (2)", 2: "A", 3: "A"})
    with pytest.raises(ValidationError, match="3 records gave 2 distinct keys"):
        tasks._balance_sheet([_data(2023, 1), _data(2023, 2), _data(2023, 3)])
    with pytest.raises(ValidationError, match="2 records gave 1 distinct keys"):
        tasks._balance_sheet([_data(2023, 1), _data(2023, 2)])


def test_balance_sheet_without_records_is_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Recorded: wheat for Bermuda (BD) in 2023 answers 200 ``[]``. A balance sheet is one
    record, so an empty answer is absence (conventions §5), unlike ``get_data``'s list."""
    route = replay_fixture(DATA, "no_data_valid_codes")
    with pytest.raises(NotFoundError) as info:
        tasks.get_balance_sheet(WHEAT, "BD", 2023)
    assert "commodity 0410000, country BD, market year 2023" in str(info.value)
    assert "no records" in str(info.value)
    assert route.call_count == 1


def test_balance_sheet_for_a_market_year_without_data_is_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(DATA, "unknown_year")
    with pytest.raises(NotFoundError) as info:
        tasks.get_balance_sheet(WHEAT, "US", 1900)
    assert "commodity 0410000, country US, market year 1900" in str(info.value)
    assert "upstream answered HTTP 404" in str(info.value)
    assert route.call_count == 1


@pytest.mark.anyio
async def test_balance_sheet_through_both_adapters(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.psd.http import router

    replay_fixture(DATA, "wheat_us_2023")
    arguments: dict[str, str | int] = {
        "commodity_code": WHEAT,
        "country_code": "US",
        "market_year": 2023,
    }
    payload = await mcp_call(server, "usda_psd_get_balance_sheet", dict(arguments))
    assert "note" not in payload
    assert list(payload["data"]["attributes"]) == WHEAT_US_2023_KEYS
    assert payload["data"]["attributes"]["Production"] == {
        "attribute_id": 28,
        "unit_id": 8,
        "value": 49095.0,
        "calendar_year": 2026,
        "month": 7,
    }
    assert payload["data"]["market_year"] == 2023
    assert payload["meta"]["endpoint"] == DATA
    assert payload["meta"]["vintage"] == "2026-07"
    assert payload["meta"]["published_at"] is None
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/usda-psd/get_balance_sheet", params=arguments)
    assert response.status_code == 200, response.text
    attributes = response.json()["data"]["attributes"]
    assert list(attributes) == WHEAT_US_2023_KEYS
    assert attributes["Yield"]["value"] == 3.2719, "a JSON number (ADR-0008)"


# get_time_series


def test_get_time_series_one_request_per_year_in_order(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    routes = {year: replay_fixture(DATA, f"wheat_us_{year}") for year in (2021, 2022, 2023)}
    result = tasks.get_time_series(WHEAT, "US", AttributeId.PRODUCTION, 2021, 2023)
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
    assert result.meta.endpoint == DATA
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
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    """2022 answers PSD's 404 for a year without data: the recorded 1900 answer (empty
    body, ``text/plain``), served at the 2022 path. The year is absent, nothing filled."""
    replay_fixture(DATA, "wheat_us_2021")
    replay_fixture(DATA, "wheat_us_2023")
    missing = _mount_recorded_404(respx_mock, 2022)
    result = tasks.get_time_series(WHEAT, "US", AttributeId.EXPORTS, 2021, 2023)
    assert missing.call_count == 1
    assert len(respx_mock.calls) == 3
    assert [(r.market_year, r.value) for r in result.data] == [
        (2021, Decimal("21656.0")),
        (2023, Decimal("19212.0")),
    ]
    assert result.meta.vintage == "2026-07"


def test_a_series_without_any_record_is_empty_not_an_error(
    respx_mock: respx.MockRouter,
) -> None:
    """The recorded empty 404 for 1900 at the 1960 path: the first year a series may ask
    for is accepted, it is absent, and the series is a valid empty list."""
    route = _mount_recorded_404(respx_mock, 1960)
    result = tasks.get_time_series(WHEAT, "US", AttributeId.PRODUCTION, 1960, 1960)
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
        tasks.get_time_series(WHEAT, "US", AttributeId.PRODUCTION, 2021, 2023)
    assert not isinstance(info.value, NoDataForYear)
    assert f"api.data.gov has no route for {_path(2022)}" in str(info.value)
    assert gateway.call_count == 1
    assert later.call_count == 0, "nothing after the error is requested"


def test_a_series_of_an_attribute_the_answers_lack_is_empty(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
) -> None:
    """Area Planted (1) is a packaged attribute that wheat US does not report."""
    for year in (2021, 2022, 2023):
        replay_fixture(DATA, f"wheat_us_{year}")
    result = tasks.get_time_series(WHEAT, "US", AttributeId.AREA_PLANTED, 2021, 2023)
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


# get_top_countries


def test_get_top_countries_sorted_and_truncated(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(ALL, "wheat_all_2023")
    result = tasks.get_top_countries(WHEAT, 2023, AttributeId.PRODUCTION, 5)
    assert route.call_count == 1
    assert [(r.country_code, r.value) for r in result.data] == [
        ("CH", Decimal("136590.0")),
        ("E4", Decimal("135375.0")),  # the European Union ranks like a country
        ("IN", Decimal("110554.0")),
        ("RS", Decimal("91500.0")),
        ("US", Decimal("49095.0")),
    ]
    recorded = _recorded(ALL, "wheat_all_2023", list[CommodityData])
    assert all(record in recorded for record in result.data), "records as upstream sent them"
    assert {r.attribute_id for r in result.data} == {28}
    assert result.meta.endpoint == ALL
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 2023,
        "attribute_id": 28,
        "n": 5,
    }
    assert tasks._vintage(result.data) == "2026-09", "the five returned"
    assert result.meta.vintage == "2026-10", "every record ranked, not only the five"
    assert result.meta.published_at is None


def test_top_countries_ties_keep_upstream_order(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Wheat 2023: 123 countries report production, 44 of them 0. With ``n`` above the
    count every record comes back, and equal values in upstream's order."""
    replay_fixture(ALL, "wheat_all_2023")
    result = tasks.get_top_countries(WHEAT, 2023, AttributeId.PRODUCTION, 200)
    production = [
        r for r in _recorded(ALL, "wheat_all_2023", list[CommodityData]) if r.attribute_id == 28
    ]
    assert len(result.data) == len(production) == 123
    zeros = [r for r in result.data if r.value == 0]
    assert len(zeros) == 44
    assert zeros == [r for r in production if r.value == 0]
    assert result.data[-44:] == zeros
    values = [r.value for r in result.data]
    assert values == sorted(values, reverse=True)


def test_top_countries_default_n_is_ten(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture(ALL, "corn_all_2023")
    result = tasks.get_top_countries(CORN, 2023, AttributeId.EXPORTS)
    assert [r.country_code for r in result.data] == [
        "US",
        "BR",
        "AR",
        "UP",
        "RS",
        "E4",
        "BM",
        "TU",
        "RB",
        "SF",
    ]
    assert result.meta.request["n"] == 10


def test_top_countries_for_a_market_year_without_data_is_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(ALL, "year_1900")
    with pytest.raises(NotFoundError) as info:
        tasks.get_top_countries(WHEAT, 1900, AttributeId.PRODUCTION)
    assert "commodity 0410000, every country, market year 1900" in str(info.value)
    assert route.call_count == 1


@pytest.mark.anyio
async def test_top_countries_tool_end_to_end(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture(ALL, "wheat_all_2023")
    payload = await mcp_call(
        server,
        "usda_psd_get_top_countries",
        {"commodity_code": WHEAT, "market_year": 2023, "attribute_id": 88, "n": 3},
    )
    assert [(row["country_code"], row["value"]) for row in payload["data"]] == [
        ("RS", 55500.0),
        ("E4", 38001.0),
        ("CA", 25439.0),
    ]
    assert payload["data"][0]["unit_id"] == 8
    assert payload["meta"]["vintage"] == "2026-10"


# get_latest_release


def test_get_latest_release_is_the_newest_month_of_the_list(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(RELEASES, "wheat")
    result = tasks.get_latest_release(WHEAT)
    assert route.call_count == 1
    recorded = _recorded(RELEASES, "wheat", list[DataReleaseInfo])
    newest = max((r.release_year, r.release_month) for r in recorded)
    assert newest == (2026, 10)
    assert result.data == [r for r in recorded if (r.release_year, r.release_month) == newest]
    assert len(result.data) == 146
    assert sum(r.market_year == 2026 for r in result.data) == 123
    assert result.meta.endpoint == RELEASES
    assert result.meta.request == {"commodity_code": WHEAT}
    assert result.meta.vintage == "2026-10"
    assert result.meta.published_at is None


def test_latest_release_vintage_matches_get_data(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Same form as the data tasks' vintage: wheat 2023 for every country is 2026-10."""
    replay_fixture(RELEASES, "wheat")
    replay_fixture(ALL, "wheat_all_2023")
    assert tasks.get_latest_release(WHEAT).meta.vintage == tasks.get_data(WHEAT, 2023).meta.vintage


def test_latest_of_no_releases_is_empty() -> None:
    """Pure: a commodity without releases gives no records and no vintage."""
    assert tasks._latest([]) == ([], None)
    one = DataReleaseInfo(
        commodity_code=WHEAT,
        country_code="US",
        market_year=2023,
        release_year=2026,
        release_month=7,
    )
    assert tasks._latest([one]) == ([one], "2026-07")


@pytest.mark.anyio
async def test_latest_release_tool_end_to_end(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture(RELEASES, "wheat")
    payload = await mcp_call(server, "usda_psd_get_latest_release", {"commodity_code": WHEAT})
    assert len(payload["data"]) == 146, "under the cap of 200 rows"
    assert "note" not in payload
    assert {(row["release_year"], row["release_month"]) for row in payload["data"]} == {(2026, 10)}
    assert payload["meta"]["vintage"] == "2026-10"


# validation, before any request


def test_slices_check_their_arguments_before_any_request(respx_mock: respx.MockRouter) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    with pytest.raises(UnknownCode, match="0410000 \\(Wheat\\)"):
        tasks.get_balance_sheet("0410001", "US", 2023)
    with pytest.raises(UnknownCode, match="use get_world_data for world data"):
        tasks.get_balance_sheet(WHEAT, "00", 2023)
    with pytest.raises(UnknownCode, match="Omit country_code"):
        tasks.get_balance_sheet(WHEAT, "all", 2023)
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_balance_sheet(WHEAT, "US", 23)

    with pytest.raises(UnknownCode, match="999 is not an attribute_id") as unknown:
        tasks.get_time_series(WHEAT, "US", 999, 2021, 2023)
    assert unknown.value.closest == [("99", "Refined Exp.(Raw Val)")]
    with pytest.raises(InvalidRequestError, match="attribute_id must be an integer"):
        tasks.get_time_series(WHEAT, "US", True, 2021, 2023)
    with pytest.raises(InvalidRequestError, match="start_year 2023 is after end_year 2021"):
        tasks.get_time_series(WHEAT, "US", 28, 2023, 2021)
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_time_series(WHEAT, "US", 28, 21, 2023)
    with pytest.raises(InvalidRequestError, match="start_year must be 1960 or later") as early:
        tasks.get_time_series(WHEAT, "US", 28, 1959, 2023)
    assert "PSD Database has data for most commodities since year 1960" in str(early.value)
    with pytest.raises(InvalidRequestError, match="start_year must be 1960 or later"):
        tasks.get_time_series(WHEAT, "US", 28, 1900, 1900)
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_time_series(WHEAT, "US", 28, 2021, 20230)
    with pytest.raises(UnknownCode, match="'XX' is not a country_code"):
        tasks.get_time_series(WHEAT, "XX", 28, 2021, 2023)

    for n in (0, -1, True):
        with pytest.raises(InvalidRequestError, match="n must be a whole number of at least 1"):
            tasks.get_top_countries(SOYBEANS, 2023, 28, n)
    with pytest.raises(UnknownCode, match="attribute_id"):
        tasks.get_top_countries(SOYBEANS, 2023, 1000)
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_top_countries(SOYBEANS, 23, 28)
    with pytest.raises(UnknownCode):
        tasks.get_top_countries("soybeans", 2023, 28)

    with pytest.raises(UnknownCode) as by_name:
        tasks.get_latest_release("wheat")
    assert ("0410000", "Wheat") in by_name.value.closest
    assert not respx_mock.calls
