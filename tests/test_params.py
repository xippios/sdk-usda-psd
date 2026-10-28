"""Packaged reference lists, their enums and the argument checks built on them."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from xippios.core import InvalidRequestError, PackagedList, UnknownCode, parse
from xippios.core.http import status_for
from xippios.core.testing import load_fixture

from xippios.usda.psd import enums
from xippios.usda.psd.models import (
    Commodity,
    CommodityAttribute,
    CommodityData,
    Country,
    Region,
    UnitOfMeasure,
)
from xippios.usda.psd.params import (
    PACKAGE,
    PACKAGED_LISTS,
    attribute_names,
    validate_attribute_id,
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
FETCHED = datetime(2026, 10, 23, tzinfo=UTC)
"""The packaged lists' ``fetched``, a bare date in the files, read as 00:00 UTC (ADR-0022)."""


def test_every_packaged_list_loads_and_parses() -> None:
    assert set(PACKAGED_LISTS) == set(SOURCES)
    for name, (endpoint, model) in SOURCES.items():
        packaged = PackagedList.load(PACKAGE, name)
        assert (packaged.param, packaged.endpoint) == (name, endpoint)
        assert packaged.fetched == FETCHED
        parsed = parse(list[model], packaged.records, source="usda-psd", endpoint=endpoint)  # type: ignore[valid-type]
        assert parsed, name


def test_packaged_lists_are_the_recorded_answers_verbatim() -> None:
    for name, (endpoint, _) in SOURCES.items():
        recorded = json.loads(load_fixture(FIXTURES / endpoint / "all.json").response.body)
        assert _records(name) == recorded, name


def _records(name: str) -> list[dict[str, object]]:
    return PackagedList.load(PACKAGE, name).records


def test_enums_match_the_packaged_id_lists() -> None:
    assert enums.__all__ == ["AttributeId", "UnitId"]
    attributes = _records("commodityAttributes")
    units = _records("unitsOfMeasure")
    assert [member.value for member in enums.AttributeId] == [r["attributeId"] for r in attributes]
    assert [member.value for member in enums.UnitId] == [r["unitId"] for r in units]


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
    assert error.fetched == FETCHED
    assert error.source == "usda-psd"
    # difflib scores Rye (0451000) as close as Wheat (0410000); both are named
    assert ("0410000", "Wheat") in error.closest
    assert error.message.startswith(
        "'0410001' is not a commodity_code in the packaged commodities list (fetched "
        "2026-10-23). Did you mean "
    )
    assert "0410000 (Wheat)" in error.message
    assert error.message.endswith(
        " PSD answers unknown codes with an empty result, so the package refuses them. If "
        "upstream added it since, the packaged list needs a refresh (/refresh-reference-data)."
    )


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
    assert "Did you mean US (United States)?" in info.value.message


def test_the_recorded_unknown_country_is_refused() -> None:
    with pytest.raises(
        UnknownCode, match="'XX' is not a country_code in the packaged countries list"
    ):
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


def test_attribute_names_are_the_packaged_list() -> None:
    names = attribute_names()
    records = _records("commodityAttributes")
    assert names == {r["attributeId"]: r["attributeName"] for r in records}
    assert list(names) == [r["attributeId"] for r in records], "upstream order"
    assert names[28] == "Production"
    assert names[126] == names[173] == "Total Disappearance"
    assert names[133] == names[135] == "Fresh Dom. Consumption"


@pytest.mark.parametrize("attribute_id", [28, 88, 176, 126, 173, enums.AttributeId.PRODUCTION])
def test_known_attribute_ids_pass(attribute_id: int) -> None:
    assert validate_attribute_id(attribute_id) == attribute_id


def test_unknown_attribute_id_names_the_closest() -> None:
    with pytest.raises(UnknownCode) as info:
        validate_attribute_id(999)
    error = info.value
    assert status_for(error) == 422
    assert (error.param, error.value, error.list_name) == (
        "attribute_id",
        999,
        "commodityAttributes",
    )
    assert error.closest == (("99", "Refined Exp.(Raw Val)"),)
    assert error.source == "usda-psd"
    assert error.message.startswith(
        "999 is not an attribute_id in the packaged commodityAttributes list (fetched "
        "2026-10-23). Did you mean 99 (Refined Exp.(Raw Val))? The data operations take no "
        "attribute"
    )
    assert "list_commodity_attributes lists the ids" in error.message
    assert "PSD answers unknown codes" not in error.message, "its own reason"


@pytest.mark.parametrize("attribute_id", [True, False, "28", 28.0])
def test_attribute_ids_that_are_not_integers_are_refused(attribute_id: object) -> None:
    with pytest.raises(InvalidRequestError, match="attribute_id must be an integer"):
        validate_attribute_id(attribute_id)  # type: ignore[arg-type]


DATA_FIXTURES = [
    ("PSDData_GetCountryCommodityDataByYear", "wheat_us_2021"),
    ("PSDData_GetCountryCommodityDataByYear", "wheat_us_2022"),
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


def test_an_unknown_code_without_a_close_match_still_reads_as_sentences() -> None:
    with pytest.raises(UnknownCode) as info:
        validate_commodity_code("0000000x")
    assert info.value.closest == ()
    assert info.value.message == (
        "'0000000x' is not a commodity_code in the packaged commodities list (fetched "
        "2026-10-23). PSD answers unknown codes with an empty result, so the package refuses "
        "them. If upstream added it since, the packaged list needs a refresh "
        "(/refresh-reference-data)."
    )


@pytest.mark.parametrize(
    ("value", "hint"),
    [("all", "Omit country_code for every country"), ("ALL", "Omit country_code"),
     ("00", "use get_world_data for world data")],
)  # fmt: skip
def test_all_and_00_get_a_hint_instead_of_close_matches(value: str, hint: str) -> None:
    with pytest.raises(UnknownCode, match=hint) as info:
        validate_country_code(value)
    assert info.value.closest == ()
    assert "Did you mean" not in info.value.message
