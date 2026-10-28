"""Pydantic models mirroring upstream's payloads, one ``UpstreamModel`` per object.

Conventions §3 and ``/add-endpoint`` give the rules.

The snapshot types every PSD response as ``object`` and defines no schemas
(``definitions`` is empty in ``docs/upstream/openapi/portal-document.json``). The record
shapes below therefore come from the recorded answers, each named in its model's
docstring; every field is an assumption from that fixture, recorded 2026-10-23. No PSD
record carries a personal identifier. PSD's attribute and unit ids stay plain ``int``
here, not ``IntEnum``: an id PSD adds before the packaged lists are refreshed must not
fail an answer; ``enums.AttributeId`` and ``enums.UnitId`` name the packaged ids and
compare equal to them.
"""

from decimal import Decimal

from pydantic import Field
from xippios.core import UpstreamModel

__all__ = [
    "BalanceSheet",
    "BalanceSheetEntry",
    "Commodity",
    "CommodityAttribute",
    "CommodityData",
    "Country",
    "DataReleaseInfo",
    "Region",
    "UnitOfMeasure",
]


class Commodity(UpstreamModel):
    """One record of ``PSDData_GetCommodities`` (``GET /api/psd/commodities``).

    Shape from ``tests/fixtures/PSDData_GetCommodities/all.json`` (63 records).

    Attributes:
        commodity_code: ``commodityCode``, seven digits as text, e.g. ``"0410000"``.
        commodity_name: ``commodityName``, e.g. ``"Wheat"``.
    """

    commodity_code: str = Field(validation_alias="commodityCode")
    commodity_name: str = Field(validation_alias="commodityName")


class Country(UpstreamModel):
    """One record of ``PSDData_GetCountries`` (``GET /api/psd/countries``).

    Shape from ``tests/fixtures/PSDData_GetCountries/all.json`` (251 records, 38 of them
    without a GENC code).

    Attributes:
        country_code: ``countryCode``, two characters, e.g. ``"US"``, ``"E4"``.
        country_name: ``countryName``, e.g. ``"United States"``.
        region_code: ``regionCode``, a code of ``PSDData_GetRegions``, e.g. ``"R01"``.
        genc_code: ``gencCode``, three letters, e.g. ``"USA"``; ``None`` where upstream
            sends ``null`` (aggregates such as ``"Africa, NEC"``).
    """

    country_code: str = Field(validation_alias="countryCode")
    country_name: str = Field(validation_alias="countryName")
    region_code: str = Field(validation_alias="regionCode")
    genc_code: str | None = Field(validation_alias="gencCode")


class Region(UpstreamModel):
    """One record of ``PSDData_GetRegions`` (``GET /api/psd/regions``).

    Shape from ``tests/fixtures/PSDData_GetRegions/all.json`` (15 records).

    Attributes:
        region_code: ``regionCode``, e.g. ``"R00"``.
        region_name: ``regionName``, e.g. ``"World"``.
    """

    region_code: str = Field(validation_alias="regionCode")
    region_name: str = Field(validation_alias="regionName")


class UnitOfMeasure(UpstreamModel):
    """One record of ``PSDData_GetUnitsOfMeasure`` (``GET /api/psd/unitsOfMeasure``).

    Shape from ``tests/fixtures/PSDData_GetUnitsOfMeasure/all.json`` (42 records).

    Attributes:
        unit_id: ``unitId``, an integer, e.g. ``8``.
        unit_description: ``unitDescription`` verbatim, e.g. ``"(1000 MT)           "``:
            upstream pads every description with spaces to 20 characters, and the
            padding is kept.
    """

    unit_id: int = Field(validation_alias="unitId")
    unit_description: str = Field(validation_alias="unitDescription")


class CommodityAttribute(UpstreamModel):
    """One record of ``PSDData_GetCommodityAttributes`` (``GET /api/psd/commodityAttributes``).

    Shape from ``tests/fixtures/PSDData_GetCommodityAttributes/all.json`` (85 records).
    Names are not unique: ``"Total Disappearance"`` (126, 173) and ``"Fresh Dom.
    Consumption"`` (133, 135) appear twice each.

    Attributes:
        attribute_id: ``attributeId``, an integer, e.g. ``28``.
        attribute_name: ``attributeName``, e.g. ``"Production"``.
    """

    attribute_id: int = Field(validation_alias="attributeId")
    attribute_name: str = Field(validation_alias="attributeName")


class CommodityData(UpstreamModel):
    """One forecast record of PSD's three data operations.

    ``PSDData_GetCountryCommodityDataByYear``, ``PSDData_GetCommodityDataByYear`` (the
    ``country/all`` form) and ``PSDData_GetWorldCommodityDataByYear`` answer the same
    record: one per country (``"00"`` for the world), commodity, market year and
    attribute. Shape from the fixtures ``wheat_us_2023`` (15 records), ``corn_all_2023``
    and ``wheat_all_2023`` (1,875 and 1,845), ``soybeans_world_2023`` and
    ``wheat_world_2023`` (13 and 15). Upstream sends the years and the month as digit
    strings (``"2023"``, ``"07"``), parsed to ``int`` here as Quick Stats' ``year`` is;
    ``value`` arrives as a JSON number and becomes ``Decimal`` (ADR-0008). Nothing is
    renamed, converted or re-based: a PSD market year stays a PSD market year, PSD
    country codes are not ISO codes, and ``unit_id`` names the unit of ``value``.

    ``calendar_year`` and ``month`` are the PSD release that last revised the record:
    for wheat, market year 2023, each of the 123 countries carries exactly the
    ``releaseYear``/``releaseMonth`` that ``PSDData_GetDataReleaseInfo`` lists for it
    (e.g. US: 2026, 7), and the world records carry the latest of them (2026, 10).
    A data task's ``meta.vintage`` is the latest of them across its records, formatted
    ``"YYYY-MM"`` with the month zero-padded (``"2026-07"``).

    Attributes:
        commodity_code: ``commodityCode``, e.g. ``"0410000"`` (Wheat).
        country_code: ``countryCode``, PSD's code, e.g. ``"US"``; ``"00"`` in world records.
        market_year: ``marketYear``, PSD's market year, e.g. ``2023``.
        calendar_year: ``calendarYear``, year of the release that last revised the
            record, e.g. ``2026``.
        month: ``month``, month of that release, 1 to 12 (upstream ``"07"`` is ``7``).
        attribute_id: ``attributeId``, an integer, e.g. ``28`` (Production). Plain
            ``int`` on purpose: an id PSD adds before the packaged lists are refreshed
            must not fail the whole answer. ``enums.AttributeId`` names the packaged ids
            and compares equal to them (``AttributeId.PRODUCTION == 28``).
        unit_id: ``unitId``, an integer, e.g. ``8`` (1000 MT); plain ``int`` for the same
            reason, named by ``enums.UnitId``.
        value: ``value``, e.g. ``Decimal("49095.0")``, in the unit ``unit_id`` names.
    """

    commodity_code: str = Field(validation_alias="commodityCode")
    country_code: str = Field(validation_alias="countryCode")
    market_year: int = Field(validation_alias="marketYear")
    calendar_year: int = Field(validation_alias="calendarYear")
    month: int = Field(validation_alias="month")
    attribute_id: int = Field(validation_alias="attributeId")
    unit_id: int = Field(validation_alias="unitId")
    value: Decimal = Field(validation_alias="value")


class DataReleaseInfo(UpstreamModel):
    """One record of ``PSDData_GetDataReleaseInfo`` (``commodity/{code}/dataReleaseDates``).

    Shape from ``tests/fixtures/PSDData_GetDataReleaseInfo/wheat.json``: 7,754 records,
    one per country and market year (1960 to 2026), 145 countries, no world (``"00"``)
    record. The release is a year and a month as digit strings, no day, no time, no time
    zone; both are parsed to ``int`` and nothing is combined into a date here.

    The data records carry the same release in ``calendarYear``/``month``: in every case
    recorded with its release list (wheat 2023: US, all countries, world) the data's
    latest release equals this list's record for the same commodity, market year and
    country (or the latest across countries); the corn and soybeans recordings are
    internally consistent. So the data tasks take ``meta.vintage`` from the data and
    need no second call.
    ``get_release_dates`` serves this list for polling.

    Attributes:
        commodity_code: ``commodityCode``, e.g. ``"0410000"``.
        country_code: ``countryCode``, PSD's code, e.g. ``"US"``.
        market_year: ``marketYear``, e.g. ``2023``.
        release_year: ``releaseYear``, e.g. ``2026``.
        release_month: ``releaseMonth``, 1 to 12 (upstream ``"07"`` is ``7``).
    """

    commodity_code: str = Field(validation_alias="commodityCode")
    country_code: str = Field(validation_alias="countryCode")
    market_year: int = Field(validation_alias="marketYear")
    release_year: int = Field(validation_alias="releaseYear")
    release_month: int = Field(validation_alias="releaseMonth")


class BalanceSheetEntry(UpstreamModel):
    """One attribute of a balance sheet: a ``CommodityData`` record without its keys.

    A projection (ADR-0003, ``UpstreamModel.project``): the record's own fields under
    their names, values exactly as upstream sent them, nothing converted. The commodity,
    country and market year the record also carried sit once on ``BalanceSheet``.

    Attributes:
        attribute_id: ``attributeId``, e.g. ``28`` (Production); ``enums.AttributeId``
            names it.
        unit_id: ``unitId``, the unit of ``value``, e.g. ``8`` (1000 MT), ``4``
            (1000 HA), ``26`` (MT/HA); it differs per attribute, ``enums.UnitId`` names it.
        value: ``value``, e.g. ``Decimal("49095.0")``, in the unit ``unit_id`` names.
        calendar_year: ``calendarYear``, year of the release that last revised the
            record, e.g. ``2026``.
        month: ``month``, month of that release, 1 to 12.
    """

    attribute_id: int
    unit_id: int
    value: Decimal
    calendar_year: int
    month: int


class BalanceSheet(UpstreamModel):
    """The records of one commodity, country and market year, pivoted into one record.

    Built by ``get_balance_sheet`` from one answer of
    ``PSDData_GetCountryCommodityDataByYear``, losslessly: every record of the answer is
    one entry of ``attributes``, in upstream order, and the three fields every record
    shares are kept once here. No totals are derived, no unit converted, nothing renamed.

    Attributes:
        commodity_code: ``commodityCode`` of the records, e.g. ``"0410000"`` (Wheat).
        country_code: ``countryCode`` of the records, PSD's code, e.g. ``"US"``.
        market_year: ``marketYear`` of the records, e.g. ``2023``.
        attributes: One entry per record, keyed by the attribute's upstream name as the
            packaged ``commodityAttributes`` list spells it (``"Production"``,
            ``"Ending Stocks"``). A name the list gives to several ids always carries the
            id, ``"Total Disappearance (126)"`` (today 126, 173, 133 and 135), so an id
            has the same key in every answer of a package version; an id the packaged
            list lacks is keyed ``"attribute <id>"``. A reference refresh that renames an
            attribute or adds an id under an existing name changes keys: a breaking
            change (conventions §12), recorded in the CHANGELOG.
    """

    commodity_code: str
    country_code: str
    market_year: int
    attributes: dict[str, BalanceSheetEntry]
