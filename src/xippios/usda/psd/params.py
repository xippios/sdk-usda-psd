"""Packaged PSD reference lists and the argument checks built on them (conventions §3).

The five small, stable lists PSD publishes, commodities, countries, regions, units of
measure and commodity attributes, ship inside the package under ``reference/`` so
lookups and argument checks need no network call. ``scripts/refresh_reference.py``
writes them through the ``api/`` wrappers, never by hand, and regenerates the
``AttributeId`` and ``UnitId`` enums in ``enums.py``; ``reference/README.md`` carries
the provenance of every file. Each file keeps upstream's records verbatim, under
upstream's field names; core's ``PackagedList.load(PACKAGE, name)`` reads one. Each list
that names a record's codes is declared once, ``PackagedList.codes`` (sdk-core ADR-0045):
``COMMODITIES``, ``COUNTRIES``, ``REGIONS``, ``UNITS`` and ``ATTRIBUTES``, the ``NamedBy`` of
``models`` (sdk-core ADR-0067, decision 6), so every answer names the codes of its rows in
``meta.names``; ``ATTRIBUTES.check`` refuses an attribute id, or a list of them, that the list
lacks. Each refusal before a request says that nothing was sent, core's and the package's own
(conventions §5).

Refresh policy: ``/refresh-reference-data`` runs inside ``/release-prep``, and whenever
a validation failure names a code the package lacks.
"""

import functools
import re
from collections.abc import Mapping, Sequence
from datetime import datetime

from xippios.core import InvalidRequestError, PackagedCodes, PackagedList, closest

from xippios.usda.psd._client import SOURCE

__all__ = [
    "ATTRIBUTES",
    "COMMODITIES",
    "COUNTRIES",
    "COUNTRY_HINTS",
    "PACKAGED_LISTS",
    "REGIONS",
    "UNITS",
    "attribute_names",
    "validate_attribute_id",
    "validate_commodity_code",
    "validate_country_code",
    "validate_market_year",
    "validate_region_code",
    "validate_since",
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

Keep in step with the ``LISTS`` of ``scripts/refresh_reference.py``, one ``Listed`` each,
which core's frame checks against it before a refresh (conventions §3).
"""

COMMODITIES: PackagedCodes = PackagedList.load(PACKAGE, "commodities").codes(
    "commodityCode", "commodityName", source=SOURCE
)
"""The packaged commodities by ``commodityCode``, each named by its ``commodityName``."""

COUNTRIES: PackagedCodes = PackagedList.load(PACKAGE, "countries").codes(
    "countryCode", "countryName", source=SOURCE
)
"""The packaged countries by ``countryCode``, each named by its ``countryName``. The world's
``"00"``, the country of every record of ``get_world_data``, is no code of it, so such an
answer says so in a note (sdk-core ADR-0067, decision 6)."""

REGIONS: PackagedCodes = PackagedList.load(PACKAGE, "regions").codes(
    "regionCode", "regionName", source=SOURCE
)
"""The packaged regions by ``regionCode``, each named by its ``regionName``. ``"R15"``, the
region of four packaged countries, is no code of it, so ``list_countries`` says so in a note
for those four."""

UNITS: PackagedCodes = PackagedList.load(PACKAGE, "unitsOfMeasure").codes(
    "unitId", "unitDescription", source=SOURCE
)
"""The packaged units by ``unitId``, each named by its ``unitDescription``, padded upstream: a
refusal and ``meta.names`` show it with its runs of white space collapsed, ``"(1000 MT)"``
(sdk-core ADR-0067, decision 2)."""

ATTRIBUTES: PackagedCodes = PackagedList.load(PACKAGE, "commodityAttributes").codes(
    "attributeId", "attributeName", source=SOURCE
)
"""The packaged commodity attributes by ``attributeId``, each named by its ``attributeName``."""


@functools.cache
def _codes(name: str, code_field: str, name_field: str) -> tuple[datetime, dict[str, str]]:
    """Fetch time and ``{code: upstream name}`` of a packaged list, in upstream order."""
    packaged = PackagedList.load(PACKAGE, name)
    codes = {str(record[code_field]): str(record[name_field]) for record in packaged.records}
    return packaged.fetched, codes


WORLD_DATA = "get_world_data (over MCP, the tool usda_psd_get_world_data)"
ATTRIBUTE_LIST = "list_commodity_attributes (over MCP, the tool usda_psd_list_commodity_attributes)"
REGION_LISTS = (
    "list_regions and list_countries (over MCP, the tools usda_psd_list_regions and "
    "usda_psd_list_countries)"
)
"""The tasks a refusal names, the one to call instead or the list of the known values, each
with its MCP tool, since an agent calls the tool (conventions §8)."""

COUNTRY_HINTS: dict[str, str] = {
    "all": "Omit country_code for every country; PSD's 'all' is a path element, not a code.",
    "00": "'00' is the world aggregate in PSD's world records, not a country code: use "
    f"{WORLD_DATA} for world data; the release list has no world record, pass market_year "
    "only.",
}
"""Values agents pass for a country that are not country codes, with what to do instead."""


_REASON = "PSD answers unknown codes with an empty result, so the package refuses them."
"""Why a code the packaged list lacks is refused before the call, for core's ``check``."""


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
    return COMMODITIES.check("commodity_code", commodity_code, reason=_REASON)


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
    return COUNTRIES.check("country_code", country_code, hints=COUNTRY_HINTS, reason=_REASON)


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
            "Nothing was sent. PSD has data for most commodities since 1960.",
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


def _closest_ids(value: object, codes: Mapping[int, str]) -> list[tuple[int, str]]:
    """Up to three packaged ids whose digits come close to ``value``'s, by core's ``closest``.

    The ids are compared as text, so a stray or a missing digit finds its id: ``999`` leads to
    ``99`` (Refined Exp.(Raw Val)), where the nearest by number would be ``195``, ``194`` and
    ``192``, which say nothing of the id meant. Core's ``check`` asks it for a text that is no
    number too, which it does not read, and then names the ids by name (sdk-core ADR-0045,
    decision 4, amended 2026-11-22).
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return []
    by_text = {str(code): name for code, name in codes.items()}
    return [(int(code), name) for code, name in closest(str(value), by_text)]


def validate_attribute_id[V: (int, Sequence[int])](attribute_id: V) -> V:
    """Check an attribute id, or a list of them, against the packaged ``commodityAttributes``.

    The data operations take no attribute parameter; a task that keeps the records of
    some attributes filters after the call, so an id the list lacks would select nothing.
    One call of core's ``check`` runs before any upstream call: it refuses the first id the
    list lacks, a value that is no integer (``True`` is not ``1``) and an empty list, each
    refusal saying that nothing was sent (conventions §5).

    Args:
        attribute_id: An integer, as ``PSDData_GetCommodityAttributes`` lists it, e.g.
            ``28`` (Production), ``88`` (Exports), ``176`` (Ending Stocks), or a list of
            them, e.g. ``[28, 88]``; ``enums.AttributeId`` members compare equal to them.

    Returns:
        The id or the list, unchanged.

    Raises:
        InvalidRequestError: When an id is not an integer, naming the integer to pass for a
            text of digits and the ids whose name holds another text, or the list is empty.
        UnknownCode: When the list lacks an id, naming up to three close ids with their
            upstream names.
    """
    return ATTRIBUTES.check(
        "attribute_id",
        attribute_id,
        closest=_closest_ids,
        reason="The data operations take no attribute; the task keeps these ids' records "
        "after the call, so an id the packaged list lacks would give an empty result, and "
        f"the package refuses it. {ATTRIBUTE_LIST} lists the ids.",
    )


@functools.cache
def _carried_regions() -> PackagedCodes:
    """The region codes the packaged countries carry, each named by the packaged regions list.

    The list that ``list_countries``' filter is checked against, in place of the packaged
    ``regions``, which lacks ``"R15"`` and holds ``"R00"``, which no country carries: ``"R15"``
    is named by its countries, ``"Africa, NEC; Fernando Po; French Equatorial Africa;
    Other"``, and the refusal names the packaged countries list and its fetch date, the list
    the codes come from (sdk-core ADR-0045).
    """
    countries = PackagedList.load(PACKAGE, "countries")
    names = {
        str(record["regionCode"]): str(record["regionName"])
        for record in PackagedList.load(PACKAGE, "regions").records
    }
    carried: dict[str, list[str]] = {}
    for record in countries.records:
        carried.setdefault(str(record["regionCode"]), []).append(str(record["countryName"]))
    records: list[dict[str, object]] = [
        {"regionCode": code, "regionName": names.get(code) or "; ".join(members)}
        for code, members in sorted(carried.items())
    ]
    return countries.model_copy(update={"records": records}).codes(
        "regionCode", "regionName", list_name="countries", source=SOURCE
    )


_REGION_HINTS: dict[str, str] = {
    "r00": "R00 (World) is in list_regions, but no country belongs to it: the world total is "
    "get_world_data's (over MCP, the tool usda_psd_get_world_data), and region_code takes a "
    "region countries belong to, as list_countries gives it, e.g. R04 (South America); omit "
    "it for every country."
}
"""A region of the packaged regions list that no country carries, with what to do instead."""


def validate_region_code(region_code: str) -> str:
    """Check a region code against the ``regionCode`` values the packaged countries carry.

    ``list_countries`` keeps the packaged countries whose ``regionCode`` equals it, so a
    code no country carries would list none, and it is refused instead (the maintainer's
    decision of 2026-11-26, https://github.com/xippios/sdk-usda-psd/issues/30). ``"R15"``
    passes, carried by four countries although ``PSDData_GetRegions`` lacks it; ``"R00"``
    (World), a region of the packaged ``regions`` list that no country belongs to, is
    refused with a hint instead of close codes.

    Args:
        region_code: A region code as ``list_countries`` gives it, e.g. ``"R01"`` (North
            America), ``"R04"`` (South America), ``"R15"``.

    Returns:
        The code, unchanged.

    Raises:
        InvalidRequestError: When ``region_code`` is not text.
        UnknownCode: Naming up to three close codes with their names in the packaged
            ``regions`` list, or for ``"R15"`` its countries' names; for a region of
            that list no country belongs to (``"R00"``, World) saying that the world is
            ``get_world_data``'s and that ``region_code`` takes a region countries
            belong to.
    """
    if not isinstance(region_code, str):
        raise InvalidRequestError(
            f"region_code must be a PSD region code such as 'R04' (South America), got "
            f"{region_code!r}. Nothing was sent. {REGION_LISTS} name the regions.",
            source=SOURCE,
        )
    return _carried_regions().check(
        "region_code",
        region_code,
        hints=_REGION_HINTS,
        reason="list_countries keeps the countries whose packaged regionCode equals it, so "
        "a code no country carries would list none, and the package refuses it. "
        f"{REGION_LISTS} name the regions.",
    )


RELEASE_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")
"""A PSD release month as ``meta.vintage`` writes it: ``"YYYY-MM"``, the month zero-padded."""


def validate_since(since: str) -> tuple[int, int]:
    """Check a release month ``"YYYY-MM"`` and return it as ``(year, month)``.

    The form ``meta.vintage`` of the data tasks takes, so a
    stored vintage passes as it is. Nothing else is read as a month: no day, no other
    separator, no unpadded month.

    Args:
        since: A PSD release month, e.g. ``"2026-09"``, ``"2024-02"``.

    Returns:
        ``(year, month)``, e.g. ``(2026, 9)``, comparable with a release record's
        ``(release_year, release_month)``.

    Raises:
        InvalidRequestError: When ``since`` is not four digits, a hyphen and a month from
            ``01`` to ``12``.
    """
    if not isinstance(since, str) or not RELEASE_MONTH.fullmatch(since):
        raise InvalidRequestError(
            f"since must be a PSD release month 'YYYY-MM' such as '2026-09', the form "
            f"meta.vintage takes, got {since!r}. Nothing was sent.",
            source=SOURCE,
        )
    return int(since[:4]), int(since[5:])
