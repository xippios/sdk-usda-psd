"""The five list tasks answer from the packaged lists and never call upstream.

The packaged files hold the records of the answers recorded in
``tests/fixtures/<wrapper>/all.json`` (the refresh of 2026-10-28 fetched the same records),
so a task returning exactly what the endpoint wrapper parses from that recording proves
the package answers what upstream answered.
Every test here runs with ``respx`` active: a request no route matches fails loudly, and
each test checks that the tasks sent none. ``meta`` is core's ``PackagedList.meta``
(ADR-0022, rule 1): ``retrieved_at`` the list's fetch time, ``vintage`` ``None``, and
``request`` without the filters left ``None``. Counts are read from the packaged files,
never pinned: a refresh changes them.
"""

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
import respx
from pydantic import BaseModel
from xippios.core import PackagedList
from xippios.core.testing import mcp_call

from xippios.usda.psd import api, tasks
from xippios.usda.psd.mcp import server
from xippios.usda.psd.models import (
    Commodity,
    CommodityAttribute,
    Country,
    Region,
    UnitOfMeasure,
)
from xippios.usda.psd.params import PACKAGE

LISTS: list[tuple[str, str, str, type[BaseModel]]] = [
    # task, packaged list, operation it came from (meta.endpoint, verbatim), record model
    ("list_commodities", "commodities", "PSDData_GetCommodities", Commodity),
    ("list_countries", "countries", "PSDData_GetCountries", Country),
    ("list_regions", "regions", "PSDData_GetRegions", Region),
    ("list_units_of_measure", "unitsOfMeasure", "PSDData_GetUnitsOfMeasure", UnitOfMeasure),
    (
        "list_commodity_attributes",
        "commodityAttributes",
        "PSDData_GetCommodityAttributes",
        CommodityAttribute,
    ),
]
IDS = [task for task, *_ in LISTS]
WRAPPERS = {
    "PSDData_GetCommodities": "get_commodities",
    "PSDData_GetCountries": "get_countries",
    "PSDData_GetRegions": "get_regions",
    "PSDData_GetUnitsOfMeasure": "get_units_of_measure",
    "PSDData_GetCommodityAttributes": "get_commodity_attributes",
}
"""Each operation's wrapper in ``api/``, its name in snake case without ``PSDData_``
(conventions §2), which also names its fixture directory (§10)."""
CAP = 200
"""The family's default MCP result cap in rows (conventions §8); ``list_countries`` has a
cap of its own, ``tasks.MCP_CAPS`` (ADR-0016)."""
FETCHED: dict[str, datetime] = {
    "commodities": datetime(2026, 10, 28, 21, 42, 3, tzinfo=UTC),
    "countries": datetime(2026, 10, 28, 21, 42, 3, tzinfo=UTC),
    "regions": datetime(2026, 10, 28, 21, 42, 4, tzinfo=UTC),
    "unitsOfMeasure": datetime(2026, 10, 28, 21, 42, 5, tzinfo=UTC),
    "commodityAttributes": datetime(2026, 10, 28, 21, 42, 6, tzinfo=UTC),
}
"""Each packaged list's ``fetched``: the UTC time of its fetch in the refresh of 2026-10-28,
to the second, as ``PackagedList.write`` wrote it (ADR-0022, amendment 2026-10-27)."""


def _packaged(name: str) -> PackagedList:
    """The packaged list, read from its file by core's ``PackagedList``."""
    return PackagedList.load(PACKAGE, name)


def _upstream_fields(model: type[BaseModel]) -> set[str]:
    """The model's fields as upstream names them, the keys of a packaged record."""
    return {
        info.validation_alias if isinstance(info.validation_alias, str) else name
        for name, info in model.model_fields.items()
    }


@pytest.mark.parametrize(("task", "name", "endpoint", "model"), LISTS, ids=IDS)
def test_every_packaged_list_is_upstreams_records_with_their_provenance(
    task: str, name: str, endpoint: str, model: type[BaseModel]
) -> None:
    """Structure, not counts: each record carries the list's fields under upstream's
    names, and the file names its operation and its fetch time."""
    packaged = _packaged(name)
    assert (packaged.param, packaged.endpoint) == (name, endpoint)
    assert packaged.fetched.tzinfo is UTC
    assert packaged.records, name
    fields = _upstream_fields(model)
    assert all(set(record) == fields for record in packaged.records), name


def test_every_list_task_is_exported() -> None:
    import xippios.usda.psd as package

    for task in IDS:
        assert task in tasks.__all__
        assert task in package.__all__
        assert getattr(package, task) is getattr(tasks, task)


@pytest.mark.anyio
@pytest.mark.parametrize(("task", "name", "endpoint", "model"), LISTS, ids=IDS)
async def test_list_answers_the_recorded_records_without_a_call(
    replay_fixture: Callable[[str, str], respx.Route],
    respx_mock: respx.MockRouter,
    task: str,
    name: str,
    endpoint: str,
    model: type[BaseModel],
) -> None:
    """The recording is mounted, so a call would succeed silently; none is made."""
    route = replay_fixture(WRAPPERS[endpoint], "all")
    result = await getattr(tasks, f"{task}_async")()
    assert not respx_mock.calls, f"{task} called upstream"
    recorded = await getattr(api, WRAPPERS[endpoint])()
    assert route.call_count == 1, "the one call is the wrapper's"
    assert result.data == recorded, "same records, same values, upstream order"
    assert len(result.data) == len(_packaged(name).records)
    assert all(type(record) is model for record in result.data)
    assert result.meta.source == "usda-psd"
    assert result.meta.endpoint == endpoint
    assert result.meta.retrieved_at == _packaged(name).fetched == FETCHED[name], (
        "retrieved_at is when the package fetched the list, the file's UTC time to the second"
    )
    assert result.meta.vintage is None, "a fetch date is not a release identifier"
    assert result.meta.published_at is None
    assert result.meta.request == {}, "a filter left None is left out"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task", "name", "endpoint"),
    [(task, name, endpoint) for task, name, endpoint, _ in LISTS],
    ids=IDS,
)
async def test_list_tool_end_to_end(
    respx_mock: respx.MockRouter, task: str, name: str, endpoint: str
) -> None:
    """Every list reaches an agent whole: ``list_countries`` through its own cap."""
    payload = await mcp_call(server, f"usda_psd_{task}", {})
    rows = [record.model_dump(mode="json") for record in getattr(tasks, task)().data]
    assert payload["data"] == rows
    assert "note" not in payload
    assert payload["meta"]["source"] == "usda-psd"
    assert payload["meta"]["endpoint"] == endpoint
    assert datetime.fromisoformat(payload["meta"]["retrieved_at"]) == _packaged(name).fetched
    assert payload["meta"]["vintage"] is None
    assert payload["meta"]["published_at"] is None
    assert payload["meta"]["request"] == {}
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_countries_over_mcp_are_whole_without_a_filter_and_with_one(
    respx_mock: respx.MockRouter,
) -> None:
    """More countries than the default cap of 200 rows: ``list_countries``'s own cap
    (``tasks.MCP_CAPS``, ADR-0016) lets every one through, the United States included, and
    every region and a search come back whole as well."""
    every = await mcp_call(server, "usda_psd_list_countries", {})
    countries = tasks.list_countries().data
    assert every["data"] == [country.model_dump(mode="json") for country in countries]
    assert len(every["data"]) > CAP, "past the default cap"
    assert "note" not in every
    assert "US" in {row["country_code"] for row in every["data"]}
    regions = Counter(country.region_code for country in countries)
    for region_code, count in regions.items():
        payload = await mcp_call(server, "usda_psd_list_countries", {"region_code": region_code})
        assert len(payload["data"]) == count, region_code
        assert "note" not in payload, region_code
        assert payload["meta"]["request"] == {"region_code": region_code}
    united = await mcp_call(server, "usda_psd_list_countries", {"search": "united"})
    assert [row["country_code"] for row in united["data"]] == ["TC", "UK", "US"]
    assert "note" not in united
    assert not respx_mock.calls


def test_list_countries_by_region(respx_mock: respx.MockRouter) -> None:
    every = tasks.list_countries().data
    north_america = tasks.list_countries(region_code="R01")
    assert [c.country_code for c in north_america.data] == ["CA", "GL", "MX", "SB", "US"]
    assert north_america.data == [c for c in every if c.region_code == "R01"], "upstream order"
    assert north_america.meta.request == {"region_code": "R01"}
    by_region = {
        code: tasks.list_countries(region_code=code).data for code in {c.region_code for c in every}
    }
    assert sum(len(countries) for countries in by_region.values()) == len(every)
    assert not respx_mock.calls


def test_region_r15_is_filtered_though_list_regions_lacks_it(
    respx_mock: respx.MockRouter,
) -> None:
    """Upstream as recorded: four countries sit in R15, which ``PSDData_GetRegions`` does
    not list; the filter selects them all the same."""
    r15 = tasks.list_countries(region_code="R15")
    assert [(c.country_code, c.country_name) for c in r15.data] == [
        ("T3", "Africa, NEC"),
        ("T8", "Fernando Po"),
        ("T4", "French Equatorial Africa"),
        ("ZZ", "Other"),
    ]
    assert {c.genc_code for c in r15.data} == {None}
    assert "R15" not in {r.region_code for r in tasks.list_regions().data}
    assert r15.meta.request == {"region_code": "R15"}
    assert not respx_mock.calls


def test_an_unknown_region_is_an_empty_list(respx_mock: respx.MockRouter) -> None:
    """No validation: a region no country carries has no countries, a correct answer."""
    unknown = tasks.list_countries(region_code="R99")
    assert unknown.data == []
    assert unknown.meta.request == {"region_code": "R99"}
    assert unknown.meta.retrieved_at == FETCHED["countries"]
    assert unknown.meta.vintage is None
    assert tasks.list_countries(region_code="r01").data == [], "exact, as list_regions spells it"
    assert not respx_mock.calls


def test_list_countries_search_matches_code_or_name_ignoring_case(
    respx_mock: respx.MockRouter,
) -> None:
    united = tasks.list_countries(search="united")
    assert [c.country_code for c in united.data] == ["TC", "UK", "US"]
    assert united.meta.request == {"search": "united"}
    assert tasks.list_countries(search="UNITED").data == united.data
    assert [c.country_name for c in tasks.list_countries(search="e4").data] == ["European Union"]
    assert [c.country_code for c in tasks.list_countries(search="us").data] == [
        "AS",  # Australia
        "AU",  # Austria
        "BO",  # Belarus
        "CY",  # Cyprus
        "MP",  # Mauritius
        "RS",  # Russia
        "NQ",  # Trust Territory of the Pacific
        "US",  # by its code and its name
    ], "SU Sudan is not one: code and name are matched one at a time, never joined"
    assert [c.country_code for c in tasks.list_countries(search="E4").data] == ["E4"]
    both = tasks.list_countries(region_code="R01", search="united")
    assert [c.country_code for c in both.data] == ["US"]
    assert both.meta.request == {"region_code": "R01", "search": "united"}
    assert tasks.list_countries(search="atlantis").data == []
    assert not respx_mock.calls


def test_list_countries_search_matches_the_genc_code(respx_mock: respx.MockRouter) -> None:
    """``"usa"`` occurs in no PSD code or name, only in the United States' GENC code."""
    usa = tasks.list_countries(search="usa")
    assert [(c.country_code, c.country_name, c.genc_code) for c in usa.data] == [
        ("US", "United States", "USA")
    ]
    assert usa.meta.request == {"search": "usa"}
    assert tasks.list_countries(search="USA").data == usa.data
    assert [c.country_code for c in tasks.list_countries(search="gbr").data] == ["UK"]
    assert [c.country_code for c in tasks.list_countries(search="deu").data] == ["GM"]
    assert [c.country_code for c in tasks.list_countries(search="che").data] == [
        "SE",  # Seychelles, by its name
        "SZ",  # Switzerland, by its GENC code CHE
    ]
    assert not respx_mock.calls


def test_list_countries_search_skips_a_null_genc_code(respx_mock: respx.MockRouter) -> None:
    """Upstream sends ``gencCode: null`` for 38 countries; a search passes over the null
    without raising and still finds them by code or name."""
    every = tasks.list_countries().data
    assert sum(c.genc_code is None for c in every) == 38
    africa_nec = tasks.list_countries(search="africa, nec").data
    assert [(c.country_code, c.genc_code) for c in africa_nec] == [("T3", None)]
    assert [c.country_code for c in tasks.list_countries(search="t3").data] == ["T3"]
    assert tasks.list_countries(search="none").data == [], "a null is not the text 'None'"
    nulls = [c for c in tasks.list_countries(search="").data if c.genc_code is None]
    assert len(nulls) == 38, "an empty search keeps every country, nulls included"
    assert not respx_mock.calls


def test_list_commodities_search(respx_mock: respx.MockRouter) -> None:
    wheat = tasks.list_commodities(search="wheat")
    assert wheat.data == [Commodity(commodity_code="0410000", commodity_name="Wheat")]
    assert wheat.meta.request == {"search": "wheat"}
    assert tasks.list_commodities(search="WHEAT").data == wheat.data
    assert [c.commodity_name for c in tasks.list_commodities(search="0440000").data] == ["Corn"]
    assert [c.commodity_code for c in tasks.list_commodities(search="soybean").data] == [
        "0813100",
        "0813101",
        "4232000",
        "4232001",
        "2222000",
        "2222001",
    ]
    assert tasks.list_commodities(search="unobtainium").data == []
    assert not respx_mock.calls


def test_list_commodity_attributes_search(respx_mock: respx.MockRouter) -> None:
    """Names are not unique upstream; both ids of a name come back, in upstream order."""
    total = tasks.list_commodity_attributes(search="Total Disappearance")
    assert [(a.attribute_id, a.attribute_name) for a in total.data] == [
        (126, "Total Disappearance"),
        (173, "Total Disappearance"),
    ]
    assert total.meta.request == {"search": "Total Disappearance"}
    disappearance = tasks.list_commodity_attributes(search="disappearance").data
    assert [a.attribute_id for a in disappearance] == [126, 151, 173]
    by_id = tasks.list_commodity_attributes(search="28").data
    assert [(a.attribute_id, a.attribute_name) for a in by_id] == [
        (28, "Production"),
        (128, "Dom. Leaf Consumption"),
    ]
    assert not respx_mock.calls


def test_units_keep_upstream_padding(respx_mock: respx.MockRouter) -> None:
    units = tasks.list_units_of_measure().data
    assert units[7] == UnitOfMeasure(unit_id=8, unit_description="(1000 MT)           ")
    assert all(len(u.unit_description) == 20 for u in units), "upstream's padding is kept"
    assert not respx_mock.calls


def test_list_routes_are_whole_over_http(respx_mock: respx.MockRouter) -> None:
    """The cap is the MCP server's; HTTP answers every record."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.psd.http import router

    app = FastAPI()
    app.include_router(router)
    http = TestClient(app)
    countries = http.get("/usda-psd/list_countries")
    assert countries.status_code == 200, countries.text
    assert len(countries.json()["data"]) == len(_packaged("countries").records)
    assert "note" not in countries.json()
    r15 = http.get("/usda-psd/list_countries", params={"region_code": "R15"}).json()
    assert [row["country_code"] for row in r15["data"]] == ["T3", "T8", "T4", "ZZ"]
    assert datetime.fromisoformat(r15["meta"]["retrieved_at"]) == FETCHED["countries"]
    assert r15["meta"]["vintage"] is None
    regions = http.get("/usda-psd/list_regions").json()
    assert len(regions["data"]) == len(_packaged("regions").records)
    assert regions["meta"]["request"] == {}
    assert not respx_mock.calls
