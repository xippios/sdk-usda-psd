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
from xippios.core import (
    InvalidRequestError,
    NotFoundError,
    PackagedList,
    UnknownCode,
    ValidationError,
    parse,
)
from xippios.core.testing import (
    ReplayFixture,
    assert_projection,
    fixture_path,
    load_fixture,
    mcp_call,
    mcp_call_text,
)

from xippios.usda.psd import tasks
from xippios.usda.psd.enums import AttributeId, UnitId
from xippios.usda.psd.errors import NoDataForYear
from xippios.usda.psd.mcp import server
from xippios.usda.psd.models import BalanceSheetEntry, CommodityData, DataReleaseInfo
from xippios.usda.psd.params import PACKAGE, attribute_names, country_regions

FIXTURES = Path(__file__).parent / "fixtures"
WHEAT, CORN, SOYBEANS = "0410000", "0440000", "2222000"
DATA = "get_country_commodity_data_by_year"
ALL = "get_commodity_data_by_year"
RELEASES = "get_data_release_info"
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


OPERATIONS = {
    DATA: "PSDData_GetCountryCommodityDataByYear",
    ALL: "PSDData_GetCommodityDataByYear",
    RELEASES: "PSDData_GetDataReleaseInfo",
}
"""The upstream operation behind each fixture directory ``_recorded`` reads, verbatim, as
the wrapper passes it to ``parse`` and as ``meta.endpoint`` carries it."""


def _recorded[T](directory: str, case: str, kind: type[list[T]]) -> list[T]:
    """The recorded answer parsed as the wrapper parses it, without a request: under the
    verbatim operation id, so a parse failure names upstream's operation."""
    body = json.loads(load_fixture(fixture_path(FIXTURES, directory, case)).response.body)
    return parse(kind, body, source="usda-psd", endpoint=OPERATIONS[directory])


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
    assert result.meta.endpoint == "PSDData_GetCountryCommodityDataByYear"
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


BALANCE_SHEET_KEYS: dict[int, str] = {
    1: "Area Planted",
    4: "Area Harvested",
    5: "Catch For Reduction",
    6: "Cows In Milk",
    7: "Crush",
    20: "Beginning Stocks",
    22: "Sow Beginning Stocks",
    23: "Dairy Cows Beg. Stocks",
    25: "Beef Cows Beg. Stocks",
    28: "Production",
    29: "Arabica Production",
    30: "Beet Sugar Production",
    31: "Commercial Production",
    32: "Cows Milk Production",
    33: "Farm Sales Weight Prod",
    34: "Filter Production",
    43: "Cane Sugar Production",
    47: "Non-Comm. Production",
    48: "Non-Filter Production",
    49: "Other Milk Production",
    53: "Robusta Production",
    54: "Rough Production",
    56: "Other Production",
    57: "Imports",
    58: "Bean Imports",
    62: "Intra-EU Imports",
    63: "MY Imp. from U.S.",
    64: "Raw Imports",
    65: "U.S. Leaf Imports",
    71: "Other Imports",
    74: "Refined Imp.(Raw Val)",
    75: "Roast & Ground Imports",
    81: "TY Imports",
    82: "Soluble Imports",
    84: "TY Imp. from U.S.",
    86: "Total Supply",
    88: "Exports",
    89: "Raw Exports",
    90: "Bean Exports",
    94: "Intra EU Exports",
    99: "Refined Exp.(Raw Val)",
    104: "Other Exports",
    107: "Roast & Ground Exports",
    113: "TY Exports",
    114: "Soluble Exports",
    117: "Total Slaughter",
    118: "Cow Slaughter",
    121: "Sow Slaughter",
    122: "Calf Slaughter",
    125: "Domestic Consumption",
    126: "Total Disappearance (126)",
    128: "Dom. Leaf Consumption",
    130: "Feed Dom. Consumption",
    131: "Fluid Use Dom. Consum.",
    132: "For Processing",
    133: "Fresh Dom. Consumption (133)",
    135: "Fresh Dom. Consumption (135)",
    139: "Human Dom. Consumption",
    140: "Industrial Dom. Cons.",
    141: "Rst,Ground Dom. Consum",
    142: "Domestic Use",
    147: "Factory Use Consum.",
    149: "Food Use Dom. Cons.",
    150: "Loss",
    151: "Other Disappearance",
    152: "Other Use, Losses",
    154: "Soluble Dom. Cons.",
    155: "U.S. Leaf Dom. Cons.",
    158: "Feed Use Dom. Consum.",
    161: "Feed Waste Dom. Cons.",
    167: "Other Foreign Cons.",
    169: "Withdrawal From Market",
    172: "Loss and Residual",
    173: "Total Disappearance (173)",
    174: "Total Use",
    175: "Total Utilization",
    176: "Ending Stocks",
    178: "Total Distribution",
    181: "Extr. Rate, 999.9999",
    182: "Milling Rate (.9999)",
    183: "Seed to Lint Ratio",
    184: "Yield",
    192: "FSI Consumption",
    194: "SME",
    195: "Stocks-to-Use",
}
"""The ``BalanceSheet.attributes`` key of every packaged attribute id, written out: the
public keys of ``get_balance_sheet`` in this package version (packaged list fetched
2026-10-23)."""


def test_balance_sheet_keys_of_every_packaged_attribute_are_pinned() -> None:
    """The guard of a reference refresh: the key ``get_balance_sheet`` gives each packaged
    id, derived from the packaged ``commodityAttributes``, equals the mapping written out
    above. A refresh that renames an attribute, or adds an id under a name another id
    has (which suffixes both with their ids), fails here, and the diff names the id and
    both keys: a breaking change, which ``CHANGELOG.md`` records under Unreleased
    (conventions §12) in the PR that updates this mapping. A new id under a name of its
    own fails as well and only adds a key."""
    names = attribute_names()
    sheet = tasks._balance_sheet([_data(2023, attribute_id) for attribute_id in names])
    derived = {entry.attribute_id: key for key, entry in sheet.attributes.items()}
    assert derived == BALANCE_SHEET_KEYS


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
    with pytest.raises(NoDataForYear) as info:
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
    assert payload["meta"]["endpoint"] == "PSDData_GetCountryCommodityDataByYear"
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
    assert f"api.data.gov has no route for {_path(2022)}" in str(info.value)
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
    the HTTP route is a ``POST`` with a JSON body (conventions §9, ADR-0007). A value the
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


# get_top_countries


def test_get_top_countries_sorted_and_truncated(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """On the cut ``wheat_all_2023`` (ADR-0019), which keeps the countries from AF to RS
    in upstream's order by country code: the United States is not in it."""
    route = replay_fixture(ALL, "wheat_all_2023")
    result = tasks.get_top_countries(WHEAT, 2023, AttributeId.PRODUCTION, 5)
    assert route.call_count == 1
    assert [(r.country_code, r.value) for r in result.data] == [
        ("CH", Decimal("136590.0")),
        ("E4", Decimal("135375.0")),  # the European Union ranks like a country
        ("IN", Decimal("110554.0")),
        ("RS", Decimal("91500.0")),
        ("CA", Decimal("33414.0")),
    ]
    recorded = _recorded(ALL, "wheat_all_2023", list[CommodityData])
    assert all(record in recorded for record in result.data), "records as upstream sent them"
    assert {r.attribute_id for r in result.data} == {28}
    assert result.meta.endpoint == "PSDData_GetCommodityDataByYear"
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 2023,
        "attribute_id": 28,
        "n": 5,
        "exclude_groupings": False,
    }
    assert tasks._vintage(result.data) == "2026-09", "the five returned"
    assert result.meta.vintage == "2026-10", "every record ranked, not only the five"
    assert result.meta.published_at is None


def test_top_countries_ties_keep_upstream_order(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """With ``n`` above the count every production record comes back, and equal values,
    the many zeros, in upstream's order."""
    replay_fixture(ALL, "wheat_all_2023")
    result = tasks.get_top_countries(WHEAT, 2023, AttributeId.PRODUCTION, 200)
    production = [
        r for r in _recorded(ALL, "wheat_all_2023", list[CommodityData]) if r.attribute_id == 28
    ]
    assert len(result.data) == len(production)
    zeros = [r for r in result.data if r.value == 0]
    assert len(zeros) > 1
    assert zeros == [r for r in production if r.value == 0]
    assert result.data[-len(zeros) :] == zeros
    values = [r.value for r in result.data]
    assert values == sorted(values, reverse=True)


def test_top_countries_default_n_is_ten(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """On the cut ``corn_all_2023``, AF to RH: the United States is not in it."""
    replay_fixture(ALL, "corn_all_2023")
    result = tasks.get_top_countries(CORN, 2023, AttributeId.EXPORTS)
    assert [r.country_code for r in result.data] == [
        "BR",
        "AR",
        "E4",
        "BM",
        "RB",
        "CA",
        "PA",
        "PK",
        "CB",
        "MD",
    ]
    assert result.meta.request["n"] == 10


def test_top_countries_of_one_region(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """``region_code`` maps each record's country through the packaged list (the records
    carry no region); the vintage is that of the region's records, the ranked set."""
    replay_fixture(ALL, "wheat_all_2023")
    result = tasks.get_top_countries(WHEAT, 2023, AttributeId.PRODUCTION, 5, region_code="R04")
    assert [(r.country_code, r.value) for r in result.data] == [
        ("AR", Decimal("15850.0")),
        ("BR", Decimal("8097.0")),
        ("CI", Decimal("1189.0")),
        ("PA", Decimal("1078.0")),
        ("BL", Decimal("293.0")),
    ]
    regions = country_regions()
    recorded = _recorded(ALL, "wheat_all_2023", list[CommodityData])
    south_america = [
        r for r in recorded if r.attribute_id == 28 and regions[r.country_code] == "R04"
    ]
    assert result.meta.vintage == tasks._vintage(south_america) == "2026-09"
    assert tasks._vintage([r for r in recorded if r.attribute_id == 28]) == "2026-10", "all"
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 2023,
        "attribute_id": 28,
        "n": 5,
        "region_code": "R04",
        "exclude_groupings": False,
    }


def test_top_countries_without_groupings(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """``exclude_groupings`` leaves out ``GROUPINGS``: of those, the cut answer holds the
    European Union, second in production, which then drops out."""
    replay_fixture(ALL, "wheat_all_2023")
    recorded = _recorded(ALL, "wheat_all_2023", list[CommodityData])
    assert "E4" in {r.country_code for r in recorded}
    result = tasks.get_top_countries(WHEAT, 2023, AttributeId.PRODUCTION, 5, exclude_groupings=True)
    assert [r.country_code for r in result.data] == ["CH", "IN", "RS", "CA", "PK"]
    every = tasks.get_top_countries(WHEAT, 2023, 28, 200, exclude_groupings=True)
    ranked = [r for r in recorded if r.attribute_id == 28 and r.country_code not in tasks.GROUPINGS]
    assert sorted(every.data, key=lambda r: r.country_code) == ranked
    assert every.meta.vintage == tasks._vintage(ranked)
    assert result.meta.request["exclude_groupings"] is True
    union = tasks.get_top_countries(WHEAT, 2023, 28, region_code="R05", exclude_groupings=True)
    assert union.data == [], "R05 holds E4 alone in this answer, a grouping"
    assert union.meta.vintage is None, "nothing ranked, no release"


def test_groupings_are_the_packaged_aggregates() -> None:
    """Every code of ``GROUPINGS`` is in the packaged countries under the name its docstring
    gives it; a reference refresh that renames or drops one fails here."""
    countries = {
        str(record["countryCode"]): record["countryName"]
        for record in PackagedList.load(PACKAGE, "countries").records
    }
    assert {code: countries.get(code) for code in tasks.GROUPINGS} == {
        "E4": "European Union",
        "E2": "EU-15",
        "E3": "EU-25",
        "C1": "Caribbean Basin",
        "T3": "Africa, NEC",
        "X8": "Southern Asia NEC",
        "Z7": "Other Pacific Islands, NEC",
        "ZZ": "Other",
    }


def test_top_countries_for_a_market_year_without_data_is_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(ALL, "year_1900")
    with pytest.raises(NoDataForYear) as info:
        tasks.get_top_countries(WHEAT, 1900, AttributeId.PRODUCTION)
    assert "commodity 0410000, every country, market year 1900" in str(info.value)
    assert route.call_count == 1


GATEWAY_NOT_FOUND = {
    "error": {
        "code": "NOT_FOUND",
        "message": "The requested URL was not found on this server.",
    }
}
"""NOT A RECORDING: api.data.gov's documented ``NOT_FOUND`` body, as ``test_client.py``
builds it."""


@pytest.mark.parametrize(
    ("path", "call"),
    [
        (_path(2023), lambda: tasks.get_balance_sheet(WHEAT, "US", 2023)),
        (_path(2023, "all"), lambda: tasks.get_top_countries(WHEAT, 2023, 28)),
    ],
    ids=["get_balance_sheet", "get_top_countries"],
)
def test_the_gateways_not_found_propagates_unchanged(
    respx_mock: respx.MockRouter, path: str, call: Callable[[], object]
) -> None:
    """Only PSD's empty 404 means "no data for this market year"; the gateway's 404 says
    the route is wrong and reaches the caller as classify raised it."""
    respx_mock.get(f"https://api.fas.usda.gov{path}").mock(
        return_value=httpx.Response(404, json=GATEWAY_NOT_FOUND)
    )
    with pytest.raises(NotFoundError) as info:
        call()
    assert not isinstance(info.value, NoDataForYear)
    assert str(info.value).startswith(f"api.data.gov has no route for {path}")


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
    filtered = await mcp_call(
        server,
        "usda_psd_get_top_countries",
        {
            "commodity_code": WHEAT,
            "market_year": 2023,
            "attribute_id": 88,
            "n": 3,
            "region_code": "R16",
            "exclude_groupings": True,
        },
    )
    assert [row["country_code"] for row in filtered["data"]] == ["RB", "BK", "MK"]
    assert filtered["meta"]["request"]["region_code"] == "R16"
    assert filtered["meta"]["request"]["exclude_groupings"] is True


# get_latest_release


def test_get_latest_release_is_the_newest_month_of_the_list(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """On the cut release list (ADR-0019), market years 1960 to 1978: its newest release
    is 2024-02, Pakistan's revision of those years."""
    route = replay_fixture(RELEASES, "wheat")
    result = tasks.get_latest_release(WHEAT)
    assert route.call_count == 1
    recorded = _recorded(RELEASES, "wheat", list[DataReleaseInfo])
    newest = max((r.release_year, r.release_month) for r in recorded)
    assert newest == (2024, 2)
    assert result.data == [r for r in recorded if (r.release_year, r.release_month) == newest]
    assert {r.country_code for r in result.data} == {"PK"}
    assert result.meta.endpoint == "PSDData_GetDataReleaseInfo"
    assert result.meta.request == {"commodity_code": WHEAT}
    assert result.meta.vintage == "2024-02"
    assert result.meta.published_at is None


def test_latest_release_since_a_stored_vintage(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Polling: a vintage older than the newest release returns that release's records, the
    stored vintage itself an empty list with ``meta.vintage`` still naming the newest
    release (2024-02 in the cut list)."""
    route = replay_fixture(RELEASES, "wheat")
    first = tasks.get_latest_release(WHEAT)
    newer = tasks.get_latest_release(WHEAT, since="2024-01")
    assert newer.data == first.data
    assert newer.meta.vintage == "2024-02"
    assert newer.meta.request == {"commodity_code": WHEAT, "since": "2024-01"}
    assert first.meta.vintage is not None
    again = tasks.get_latest_release(WHEAT, since=first.meta.vintage)
    assert again.data == [], "nothing newer than the stored vintage"
    assert again.meta.vintage == "2024-02"
    later = tasks.get_latest_release(WHEAT, since="2030-01")
    assert (later.data, later.meta.vintage) == ([], "2024-02")
    assert route.call_count == 4


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
    assert payload["data"]
    assert "note" not in payload
    assert {(row["release_year"], row["release_month"]) for row in payload["data"]} == {(2024, 2)}
    assert payload["meta"]["vintage"] == "2024-02"
    polled = await mcp_call(
        server, "usda_psd_get_latest_release", {"commodity_code": WHEAT, "since": "2024-02"}
    )
    assert polled["data"] == []
    assert polled["meta"]["vintage"] == "2024-02"
    assert polled["meta"]["request"] == {"commodity_code": WHEAT, "since": "2024-02"}


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

    for n in (0, -1, True):
        with pytest.raises(InvalidRequestError, match="n must be a whole number of at least 1"):
            tasks.get_top_countries(SOYBEANS, 2023, 28, n)
    with pytest.raises(UnknownCode, match="attribute_id"):
        tasks.get_top_countries(SOYBEANS, 2023, 1000)
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_top_countries(SOYBEANS, 23, 28)
    with pytest.raises(UnknownCode):
        tasks.get_top_countries("soybeans", 2023, 28)
    with pytest.raises(UnknownCode, match="'R99' is not a region_code") as region:
        tasks.get_top_countries(SOYBEANS, 2023, 28, region_code="R99")
    assert region.value.closest == (("R09", "Middle East"),)
    with pytest.raises(InvalidRequestError, match="exclude_groupings must be true or false"):
        tasks.get_top_countries(SOYBEANS, 2023, 28, exclude_groupings=1)  # type: ignore[arg-type]

    with pytest.raises(UnknownCode) as by_name:
        tasks.get_latest_release("wheat")
    assert ("0410000", "Wheat") in by_name.value.closest
    with pytest.raises(InvalidRequestError, match="since must be a PSD release month"):
        tasks.get_latest_release(WHEAT, since="2026-10-01")
    assert not respx_mock.calls
