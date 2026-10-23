"""Pydantic models mirroring USDA FAS PSD Online payloads.

One model per upstream object, subclassing ``xippios.core.UpstreamModel``, with fields
named as upstream names them in snake_case. Where upstream spells a field differently,
``Field(validation_alias=...)`` accepts that spelling on input; never ``alias=``, which the
adapters would serialise, handing agents the upstream spelling. Within-source hygiene only:
dates become ``datetime.date``, numbers become numbers, upstream enumerations become
``StrEnum``. No cross-source normalisation (ADR-0003): an upstream concept stays an
upstream concept.

The snapshot types every PSD response as ``object`` and defines no schemas
(``definitions`` is empty in ``docs/upstream/openapi/portal-document.json``). The record
shapes below therefore come from the recorded answers, each named in its model's
docstring; every field is an assumption from that fixture, recorded 2026-10-23.
"""

from pydantic import Field
from xippios.core import UpstreamModel

__all__ = ["Commodity", "CommodityAttribute", "Country", "Region", "UnitOfMeasure"]


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
