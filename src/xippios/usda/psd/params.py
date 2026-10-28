"""Packaged PSD reference lists and the argument checks built on them (conventions §3).

The five small, stable lists PSD publishes, commodities, countries, regions, units of
measure and commodity attributes, ship inside the package under ``reference/`` so
lookups and argument checks need no network call. ``scripts/refresh_reference.py``
writes them through the ``api/`` wrappers, never by hand, and regenerates the
``AttributeId`` and ``UnitId`` enums in ``enums.py``; ``reference/README.md`` carries
the provenance of every file. Each file keeps upstream's records verbatim, under
upstream's field names; core's ``PackagedList.load(PACKAGE, name)`` reads one.

Refresh policy: ``/refresh-reference-data`` runs inside ``/release-prep``, and whenever
a validation failure names a code the package lacks.
"""

import functools
from datetime import datetime

from xippios.core import InvalidRequestError, PackagedList, UnknownCode, closest

from xippios.usda.psd._client import SOURCE

__all__ = [
    "COUNTRY_HINTS",
    "PACKAGED_LISTS",
    "attribute_names",
    "country_regions",
    "validate_attribute_id",
    "validate_commodity_code",
    "validate_country_code",
    "validate_market_year",
    "validate_region_code",
]

PACKAGE = "xippios.usda.psd"

PACKAGED_LISTS: tuple[str, ...] = (
    "commodities",
    "countries",
    "regions",
    "unitsOfMeasure",
    "commodityAttributes",
)
"""Lists that ship inside the package, named as the upstream path names them.

Keep in step with ``ID_LISTS`` and ``TABLES`` in ``scripts/refresh_reference.py``, which
checks it before a refresh.
"""


@functools.cache
def _codes(name: str, code_field: str, name_field: str) -> tuple[datetime, dict[str, str]]:
    """Fetch time and ``{code: upstream name}`` of a packaged list, in upstream order."""
    packaged = PackagedList.load(PACKAGE, name)
    codes = {str(record[code_field]): str(record[name_field]) for record in packaged.records}
    return packaged.fetched, codes


COUNTRY_HINTS: dict[str, str] = {
    "all": "Omit country_code for every country; PSD's 'all' is a path element, not a code.",
    "00": "'00' is the world aggregate in PSD's world records, not a country code: use "
    "get_world_data for world data; the release list has no world record, pass market_year "
    "only.",
}
"""Values agents pass for a country that are not country codes, with what to do instead."""


def _validate_code(
    param: str,
    value: str,
    list_name: str,
    code_field: str,
    name_field: str,
    hints: dict[str, str] | None = None,
) -> str:
    fetched, codes = _codes(list_name, code_field, name_field)
    if value in codes:
        return value
    hint = (hints or {}).get(value.strip().lower())
    raise UnknownCode(
        param,
        value,
        list_name=list_name,
        fetched=fetched,
        closest=() if hint else closest(value, codes),
        hint=hint,
        reason="PSD answers unknown codes with an empty result, so the package refuses them.",
        source=SOURCE,
    )


def validate_commodity_code(commodity_code: str) -> str:
    """Check a commodity code against the packaged ``commodities`` list.

    PSD answers an unknown code with HTTP 200 and ``[]``, the same as a query without
    data, so the check runs before any upstream call.

    Args:
        commodity_code: Seven digits as text, as ``PSDData_GetCommodities`` lists them,
            e.g. ``"0410000"`` (Wheat), ``"0440000"`` (Corn), ``"2222000"``
            (Oilseed, Soybean).

    Returns:
        The code, unchanged.

    Raises:
        UnknownCode: Naming up to three close codes with their upstream names.
    """
    return _validate_code(
        "commodity_code", commodity_code, "commodities", "commodityCode", "commodityName"
    )


def validate_country_code(country_code: str) -> str:
    """Check a country code against the packaged ``countries`` list.

    PSD answers an unknown code with HTTP 200 and ``[]``, the same as a query without
    data, so the check runs before any upstream call.

    Args:
        country_code: Two characters, as ``PSDData_GetCountries`` lists them, e.g.
            ``"US"`` (United States), ``"BR"`` (Brazil), ``"E4"`` (European Union).

    Returns:
        The code, unchanged.

    Raises:
        UnknownCode: Naming up to three close codes with their upstream names; for
            ``"all"`` saying to omit the country, for ``"00"`` to use ``get_world_data``.
    """
    return _validate_code(
        "country_code", country_code, "countries", "countryCode", "countryName", COUNTRY_HINTS
    )


def validate_market_year(market_year: int) -> int:
    """Check that a market year is a four-digit integer.

    The snapshot types ``marketYear`` as ``int32`` and says "PSD Database has data for
    most commodities since year 1960"; it states no bounds, so none are invented here
    beyond four digits. A year without data answers HTTP 404 with an empty body
    (``unknown_year.json``, 1900), which ``classify`` maps to ``NotFoundError``.

    Args:
        market_year: The market year, e.g. ``2023``, ``1960``.

    Returns:
        The year, unchanged.

    Raises:
        InvalidRequestError: When the year is not an integer from 1000 to 9999.
    """
    if isinstance(market_year, bool) or not 1000 <= market_year <= 9999:
        raise InvalidRequestError(
            f"market_year must be a four-digit year such as 2023, got {market_year!r}. "
            "PSD has data for most commodities since 1960.",
            source=SOURCE,
        )
    return market_year


def attribute_names() -> dict[int, str]:
    """``{attributeId: attributeName}`` of the packaged ``commodityAttributes`` list.

    In upstream order, names verbatim. Names are not unique upstream:
    ``"Total Disappearance"`` is 126 and 173, ``"Fresh Dom. Consumption"`` 133 and 135.
    """
    _, codes = _codes("commodityAttributes", "attributeId", "attributeName")
    return {int(code): name for code, name in codes.items()}


def validate_attribute_id(attribute_id: int) -> int:
    """Check an attribute id against the packaged ``commodityAttributes`` list.

    The data operations take no attribute parameter; a task that keeps the records of
    one attribute filters after the call, so an id the list lacks would select nothing.
    The check runs before any upstream call.

    Args:
        attribute_id: An integer, as ``PSDData_GetCommodityAttributes`` lists it, e.g.
            ``28`` (Production), ``88`` (Exports), ``176`` (Ending Stocks);
            ``enums.AttributeId`` members compare equal to them.

    Returns:
        The id, unchanged.

    Raises:
        InvalidRequestError: When the id is not an integer (``True`` is not ``1``).
        UnknownCode: When the list lacks the id, naming up to three close ids with their
            upstream names.
    """
    if isinstance(attribute_id, bool) or not isinstance(attribute_id, int):
        raise InvalidRequestError(
            f"attribute_id must be an integer id such as 28 (Production), got "
            f"{attribute_id!r}. list_commodity_attributes lists them.",
            source=SOURCE,
        )
    fetched, codes = _codes("commodityAttributes", "attributeId", "attributeName")
    if str(attribute_id) in codes:
        return attribute_id
    raise UnknownCode(
        "attribute_id",
        attribute_id,
        list_name="commodityAttributes",
        fetched=fetched,
        closest=closest(str(attribute_id), codes),
        reason="The data operations take no attribute; the task keeps this id's records "
        "after the call, so an id the packaged list lacks would give an empty result, and "
        "the package refuses it. list_commodity_attributes lists the ids.",
        source=SOURCE,
    )


def country_regions() -> dict[str, str]:
    """``{countryCode: regionCode}`` of the packaged ``countries`` list, in upstream order.

    PSD's data records carry no region; a task that selects by region maps each record's
    ``countryCode`` through this. Four countries sit in ``"R15"``, which the packaged
    ``regions`` list lacks.
    """
    _, regions = _codes("countries", "countryCode", "regionCode")
    return dict(regions)


def validate_region_code(region_code: str) -> str:
    """Check a region code against the ``regionCode`` values the packaged countries carry.

    The data operations take no region: a task that keeps one region's countries maps
    each record through the packaged ``countries`` list after the call, so a code no
    country carries would select nothing. The check runs before any upstream call.
    ``"R15"`` passes, carried by four countries although ``PSDData_GetRegions`` lacks
    it; ``"R00"`` (World) is carried by none.

    Args:
        region_code: A region code as ``list_countries`` gives it, e.g. ``"R01"`` (North
            America), ``"R04"`` (South America), ``"R15"``.

    Returns:
        The code, unchanged.

    Raises:
        UnknownCode: Naming up to three close codes with their names in the packaged
            ``regions`` list, or for ``"R15"`` its countries' names.
    """
    fetched, regions = _codes("countries", "countryCode", "regionCode")
    carried = set(regions.values())
    if region_code in carried:
        return region_code
    _, names = _codes("regions", "regionCode", "regionName")
    _, countries = _codes("countries", "countryCode", "countryName")
    known = {
        code: names.get(code)
        or "; ".join(countries[country] for country, region in regions.items() if region == code)
        for code in sorted(carried)
    }
    raise UnknownCode(
        "region_code",
        region_code,
        list_name="countries",
        fetched=fetched,
        closest=closest(region_code, known),
        reason="The data operations take no region; the task keeps the countries whose "
        "packaged regionCode equals it, so a code no country carries would rank nothing, "
        "and the package refuses it. list_regions and list_countries name the regions.",
        source=SOURCE,
    )
