"""Replay tests for the endpoint wrappers (layer 1), against recorded answers."""

from collections.abc import Callable
from decimal import Decimal

import pytest
import respx

from xippios.usda.psd import api
from xippios.usda.psd.enums import AttributeId, UnitId
from xippios.usda.psd.models import (
    Commodity,
    CommodityAttribute,
    CommodityData,
    Country,
    DataReleaseInfo,
    Region,
    UnitOfMeasure,
)

pytestmark = pytest.mark.anyio


async def test_get_commodities(
    replay_fixture: Callable[[str, str], respx.Route], placeholder_api_key: str
) -> None:
    route = replay_fixture("PSDData_GetCommodities", "all")
    commodities = await api.PSDData_GetCommodities()
    assert len(commodities) == 63
    assert commodities[0] == Commodity(
        commodity_code="0577400", commodity_name="Almonds, Shelled Basis"
    )
    by_code = {c.commodity_code: c.commodity_name for c in commodities}
    assert by_code["0410000"] == "Wheat"
    assert by_code["0440000"] == "Corn"
    assert by_code["2222000"] == "Oilseed, Soybean"
    assert all(len(c.commodity_code) == 7 for c in commodities)
    request = route.calls.last.request
    assert request.url.path == "/api/psd/commodities"
    assert request.headers["X-Api-Key"] == placeholder_api_key


async def test_get_countries(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("PSDData_GetCountries", "all")
    countries = await api.PSDData_GetCountries()
    assert len(countries) == 251
    by_code = {c.country_code: c for c in countries}
    assert by_code["US"] == Country(
        country_code="US", country_name="United States", region_code="R01", genc_code="USA"
    )
    assert by_code["T3"].genc_code is None
    assert sum(c.genc_code is None for c in countries) == 38


async def test_get_regions(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("PSDData_GetRegions", "all")
    regions = await api.PSDData_GetRegions()
    assert len(regions) == 15
    assert regions[0] == Region(region_code="R00", region_name="World")


async def test_countries_name_one_region_the_regions_list_lacks(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Upstream as recorded: four countries (T3, T8, T4, ZZ) sit in region R15, which
    ``PSDData_GetRegions`` does not list. Kept as upstream sends it."""
    replay_fixture("PSDData_GetCountries", "all")
    replay_fixture("PSDData_GetRegions", "all")
    regions = {r.region_code for r in await api.PSDData_GetRegions()}
    countries = await api.PSDData_GetCountries()
    assert {c.region_code for c in countries} - regions == {"R15"}
    assert sorted(c.country_code for c in countries if c.region_code == "R15") == [
        "T3",
        "T4",
        "T8",
        "ZZ",
    ]


async def test_get_units_of_measure(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("PSDData_GetUnitsOfMeasure", "all")
    units = await api.PSDData_GetUnitsOfMeasure()
    assert len(units) == 42
    assert units[7] == UnitOfMeasure(unit_id=8, unit_description="(1000 MT)           ")
    assert all(len(u.unit_description) == 20 for u in units), "upstream's padding is kept"


async def test_get_commodity_attributes(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("PSDData_GetCommodityAttributes", "all")
    attributes = await api.PSDData_GetCommodityAttributes()
    assert len(attributes) == 85
    assert CommodityAttribute(attribute_id=28, attribute_name="Production") in attributes
    duplicates = [a.attribute_id for a in attributes if a.attribute_name == "Total Disappearance"]
    assert duplicates == [126, 173]


async def test_models_serialise_snake_case(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("PSDData_GetCountries", "all")
    country = (await api.PSDData_GetCountries())[0]
    assert country.model_dump(mode="json") == {
        "country_code": "AF",
        "country_name": "Afghanistan",
        "region_code": "R12",
        "genc_code": "AFG",
    }


async def test_get_country_commodity_data(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture("PSDData_GetCountryCommodityDataByYear", "wheat_us_2023")
    records = await api.PSDData_GetCountryCommodityDataByYear("0410000", "US", 2023)
    assert len(records) == 15
    assert records[2] == CommodityData(
        commodity_code="0410000",
        country_code="US",
        market_year=2023,
        calendar_year=2026,
        month=7,
        attribute_id=AttributeId.PRODUCTION,
        unit_id=UnitId._1000_MT,
        value=Decimal("49095.0"),
    )
    assert records[-1].unit_id == UnitId.MT_HA
    assert records[-1].value == Decimal("3.2719")
    assert route.calls.last.request.url.path == "/api/psd/commodity/0410000/country/US/year/2023"


async def test_get_commodity_data_for_every_country(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """``country/all``, the largest answer: 1,875 records, 125 countries, 275,759 bytes."""
    route = replay_fixture("PSDData_GetCommodityDataByYear", "corn_all_2023")
    records = await api.PSDData_GetCommodityDataByYear("0440000", 2023)
    assert len(records) == 1875
    assert len({r.country_code for r in records}) == 125
    assert {r.commodity_code for r in records} == {"0440000"}
    assert {r.market_year for r in records} == {2023}
    assert route.calls.last.request.url.path == "/api/psd/commodity/0440000/country/all/year/2023"


async def test_get_world_commodity_data(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture("PSDData_GetWorldCommodityDataByYear", "soybeans_world_2023")
    records = await api.PSDData_GetWorldCommodityDataByYear("2222000", 2023)
    assert len(records) == 13
    assert {(r.country_code, r.calendar_year, r.month) for r in records} == {("00", 2026, 10)}
    production = next(r for r in records if r.attribute_id == AttributeId.PRODUCTION)
    assert production.value == Decimal("396448.0")
    assert route.calls.last.request.url.path == "/api/psd/commodity/2222000/world/year/2023"


async def test_get_data_release_info(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture("PSDData_GetDataReleaseInfo", "wheat")
    releases = await api.PSDData_GetDataReleaseInfo("0410000")
    assert len(releases) == 7754
    assert releases[0] == DataReleaseInfo(
        commodity_code="0410000",
        country_code="BL",
        market_year=1960,
        release_year=2006,
        release_month=7,
    )
    assert len({r.country_code for r in releases}) == 145
    assert "00" not in {r.country_code for r in releases}
    assert route.call_count == 1
    path = route.calls.last.request.url.path
    assert path == "/api/psd/commodity/0410000/dataReleaseDates"
