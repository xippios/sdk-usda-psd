"""Packaged reference lists, their enums and the argument checks built on them."""

import json
from pathlib import Path

import pytest
from xippios.core import InvalidRequestError, parse
from xippios.core.http import status_for
from xippios.core.testing import load_fixture

from xippios.usda.psd import enums
from xippios.usda.psd.errors import UnknownCode
from xippios.usda.psd.models import (
    Commodity,
    CommodityAttribute,
    CommodityData,
    Country,
    Region,
    UnitOfMeasure,
)
from xippios.usda.psd.params import (
    PACKAGED_LISTS,
    packaged_values,
    validate_commodity_code,
    validate_country_code,
    validate_market_year,
)

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = {
    "commodities": ("PSDData_GetCommodities", Commodity),
    "countries": ("PSDData_GetCountries", Country),
    "regions": ("PSDData_GetRegions", Region),
    "unitsOfMeasure": ("PSDData_GetUnitsOfMeasure", UnitOfMeasure),
    "commodityAttributes": ("PSDData_GetCommodityAttributes", CommodityAttribute),
}


def test_every_packaged_list_loads_and_parses() -> None:
    assert set(PACKAGED_LISTS) == set(SOURCES)
    for name, (endpoint, model) in SOURCES.items():
        packaged = packaged_values(name)
        assert packaged is not None, name
        assert (packaged.param, packaged.endpoint) == (name, endpoint)
        assert packaged.fetched.isoformat() == "2026-10-23"
        parsed = parse(list[model], packaged.records, source="usda-psd", endpoint=endpoint)  # type: ignore[valid-type]
        assert parsed, name


def test_packaged_lists_are_the_recorded_answers_verbatim() -> None:
    for name, (endpoint, _) in SOURCES.items():
        packaged = packaged_values(name)
        assert packaged is not None
        recorded = json.loads(load_fixture(FIXTURES / endpoint / "all.json").response.body)
        assert packaged.records == recorded, name


def test_unknown_list_is_none() -> None:
    assert packaged_values("not_a_list") is None


def _records(name: str) -> list[dict[str, object]]:
    packaged = packaged_values(name)
    assert packaged is not None
    return packaged.records


def test_enums_match_the_packaged_id_lists() -> None:
    assert enums.__all__ == ["AttributeId", "UnitId"]
    attributes = _records("commodityAttributes")
    units = _records("unitsOfMeasure")
    assert [member.value for member in enums.AttributeId] == [r["attributeId"] for r in attributes]
    assert [member.value for member in enums.UnitId] == [r["unitId"] for r in units]
    assert len(enums.AttributeId) == 85
    assert len(enums.UnitId) == 42


def test_enum_members_are_named_after_upstream_names() -> None:
    assert enums.AttributeId.PRODUCTION.value == 28
    assert enums.AttributeId.ENDING_STOCKS.value == 176
    assert enums.UnitId._1000_MT.value == 8
    assert enums.UnitId.MT_HA.value == 26
    # names upstream gives to two ids carry the id
    assert enums.AttributeId.TOTAL_DISAPPEARANCE_126.value == 126
    assert enums.AttributeId.TOTAL_DISAPPEARANCE_173.value == 173
    assert enums.AttributeId.FRESH_DOM_CONSUMPTION_133.value == 133
    assert enums.UnitId.BUSHELS_31.value == 31
    assert enums.UnitId.BUSHELS_36.value == 36
    assert not hasattr(enums.AttributeId, "TOTAL_DISAPPEARANCE")


def test_enum_members_compare_equal_to_upstream_ints() -> None:
    record = CommodityAttribute.model_validate({"attributeId": 28, "attributeName": "Production"})
    assert record.attribute_id == enums.AttributeId.PRODUCTION
    assert enums.AttributeId(28) is enums.AttributeId.PRODUCTION


@pytest.mark.parametrize("code", ["0410000", "0440000", "2222000"])
def test_known_commodity_codes_pass(code: str) -> None:
    assert validate_commodity_code(code) == code


def test_unknown_commodity_code_names_the_closest() -> None:
    with pytest.raises(UnknownCode) as info:
        validate_commodity_code("0410001")
    error = info.value
    assert isinstance(error, InvalidRequestError)
    assert status_for(error) == 422
    assert (error.param, error.value, error.list_name) == (
        "commodity_code",
        "0410001",
        "commodities",
    )
    # difflib scores Rye (0451000) as close as Wheat (0410000); both are named
    assert ("0410000", "Wheat") in error.closest
    assert "0410000 (Wheat)" in error.message
    assert "did you mean " in error.message
    assert "fetched 2026-10-23" in error.message


def test_a_commodity_name_leads_to_its_code() -> None:
    with pytest.raises(UnknownCode) as info:
        validate_commodity_code("wheat")
    assert ("0410000", "Wheat") in info.value.closest


def test_the_recorded_unknown_commodity_is_refused() -> None:
    with pytest.raises(UnknownCode, match="'9999999' is not a commodity_code"):
        validate_commodity_code("9999999")


@pytest.mark.parametrize("code", ["US", "BR", "E4"])
def test_known_country_codes_pass(code: str) -> None:
    assert validate_country_code(code) == code


def test_unknown_country_code_names_the_closest() -> None:
    with pytest.raises(UnknownCode) as info:
        validate_country_code("us")
    assert info.value.closest[0] == ("US", "United States")
    assert "did you mean US (United States)" in info.value.message


def test_the_recorded_unknown_country_is_refused() -> None:
    with pytest.raises(UnknownCode, match="'XX' is not a country_code in PSD's countries list"):
        validate_country_code("XX")


def test_a_country_name_leads_to_its_code() -> None:
    with pytest.raises(UnknownCode) as info:
        validate_country_code("Brazil")
    assert ("BR", "Brazil") in info.value.closest


@pytest.mark.parametrize("year", [1960, 2023, 1900, 2030])
def test_four_digit_market_years_pass(year: int) -> None:
    assert validate_market_year(year) == year


@pytest.mark.parametrize("year", [23, 999, 10000, -2023, True])
def test_other_market_years_are_refused(year: int) -> None:
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        validate_market_year(year)


DATA_FIXTURES = [
    ("PSDData_GetCountryCommodityDataByYear", "wheat_us_2023"),
    ("PSDData_GetCommodityDataByYear", "corn_all_2023"),
    ("PSDData_GetCommodityDataByYear", "wheat_all_2023"),
    ("PSDData_GetWorldCommodityDataByYear", "soybeans_world_2023"),
    ("PSDData_GetWorldCommodityDataByYear", "wheat_world_2023"),
]


def test_every_recorded_id_is_in_the_packaged_lists() -> None:
    """Reference-data freshness, not a model constraint: ``CommodityData`` keeps the ids as
    plain ``int`` so a new upstream id never fails an answer. When this fails, a recorded
    answer names an id the packaged lists lack: run ``/refresh-reference-data``."""
    attribute_ids = {member.value for member in enums.AttributeId}
    unit_ids = {member.value for member in enums.UnitId}
    for endpoint, case in DATA_FIXTURES:
        records = json.loads(load_fixture(FIXTURES / endpoint / f"{case}.json").response.body)
        assert {r["attributeId"] for r in records} <= attribute_ids, case
        assert {r["unitId"] for r in records} <= unit_ids, case


def test_an_id_the_lists_lack_still_parses() -> None:
    record = CommodityData.model_validate(
        {
            "commodityCode": "0410000",
            "countryCode": "US",
            "marketYear": "2023",
            "calendarYear": "2026",
            "month": "07",
            "attributeId": 999,
            "unitId": 999,
            "value": 1.5,
        }
    )
    assert (record.attribute_id, record.unit_id) == (999, 999)
    assert 999 not in {member.value for member in enums.AttributeId}
