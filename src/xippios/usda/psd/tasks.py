"""Task-shaped functions for USDA FAS PSD Online.

The public API (ADR-0001, layer 2). A task composes endpoint wrappers from ``api/``,
resolves pagination and reference lookups, and returns ``Result[T]`` with full
``ResultMeta``. Write the async version, derive the sync one with ``xippios.core.sync``,
and list the sync name in ``__all__``: the MCP server and the HTTP router register
exactly what is named there.

Docstrings are read by agents: one sentence first, then ``Args:`` with examples of
valid values for every parameter. ``/add-endpoint`` walks through the whole recipe.

``meta.vintage`` of the data tasks is the PSD release that last revised the result, as
upstream names it: the latest ``calendarYear``-``month`` across the records, zero-padded
(``"2026-07"``). Every record carries the release that last revised it; for one country
all records share one, for every country and the world the latest is taken. In every
case recorded with its release list (wheat 2023: US, all countries, world) this equals
``PSDData_GetDataReleaseInfo``'s record for the same commodity, market year and country
(or the latest across countries), so no extra call is needed; the corn and soybeans
recordings are internally consistent. ``meta.published_at`` stays ``None`` for every
task: PSD gives a month, no day, and the first of the month would predate the real
mid-month release, a look-ahead bias in an as-of store. ``get_release_dates`` is the way
to poll for new releases.

The ``list_*`` tasks answer from the five lists packaged under ``reference/`` and make no
upstream call. ``meta.endpoint`` is the operation the list was fetched from
(``"PSDData_GetCountries"``), ``meta.retrieved_at`` is when the task answered, and
``meta.vintage`` is the day the package fetched the list (``"2026-10-23"``, UTC), the
``fetched`` date as the file stores it: upstream gives these lists no version
identifier. Their filters (``search``, ``region_code``) only select records of the
packaged list, which keep upstream's order and values; ``meta.request`` carries them.
"""

from xippios.core import NotFoundError, Result, ResultMeta, parse, sync

from xippios.usda.psd import api
from xippios.usda.psd._client import SOURCE
from xippios.usda.psd.models import (
    Commodity,
    CommodityAttribute,
    CommodityData,
    Country,
    DataReleaseInfo,
    Region,
    UnitOfMeasure,
)
from xippios.usda.psd.params import (
    PackagedList,
    packaged_values,
    validate_commodity_code,
    validate_country_code,
    validate_market_year,
)

__all__ = [
    "get_data",
    "get_release_dates",
    "get_world_data",
    "list_commodities",
    "list_commodity_attributes",
    "list_countries",
    "list_regions",
    "list_units_of_measure",
]


def _vintage(records: list[CommodityData]) -> str | None:
    """The latest ``calendarYear``-``month`` across ``records``, zero-padded; ``None`` if empty."""
    if not records:
        return None
    year, month = max((record.calendar_year, record.month) for record in records)
    return f"{year:04d}-{month:02d}"


def _absent(
    exc: NotFoundError, commodity_code: str, country: str, market_year: int
) -> NotFoundError:
    return NotFoundError(
        f"PSD has no data for commodity {commodity_code}, {country}, market year "
        f"{market_year}: upstream answered HTTP 404 ({exc.message}). PSD has data for most "
        "commodities since 1960.",
        source=SOURCE,
    )


async def get_data_async(
    commodity_code: str, market_year: int, country_code: str | None = None
) -> Result[list[CommodityData]]:
    """PSD supply and distribution forecasts for one commodity and market year, by country.

    One record per country and attribute (area, production, imports, exports,
    consumption, stocks, ...): ``attribute_id`` and ``unit_id`` are PSD's integer ids,
    which ``enums.AttributeId`` and ``enums.UnitId`` name; ``value`` is in that unit.
    Codes and the year are checked against the packaged lists before any call; an
    unknown code raises ``InvalidRequestError`` naming the closest ones. Each record's
    ``calendar_year`` and ``month`` are the PSD release that last revised it: for one
    country all records share one release, for every country they differ by country.
    ``meta.vintage`` is the latest of them as upstream names it (``"2026-07"``);
    ``meta.published_at`` stays empty, since PSD gives no day. An empty list means PSD
    has no records for that combination; a market year without data raises
    ``NotFoundError``. The MCP server returns at most 200 rows per call, and every
    country is up to about 1,900 rows (1,875 for corn in 2023), so pass
    ``country_code`` to narrow.

    Args:
        commodity_code: PSD commodity code, seven digits, e.g. ``"0410000"`` (Wheat),
            ``"0440000"`` (Corn), ``"2222000"`` (Oilseed, Soybean).
        market_year: PSD market year, e.g. ``2023``; data goes back to 1960 for most
            commodities.
        country_code: PSD country code (not ISO), e.g. ``"US"`` (United States), ``"BR"``
            (Brazil), ``"E4"`` (European Union). Omit it (``None``) for every country:
            one record per country and attribute. For the world total use
            ``get_world_data``.
    """
    validate_commodity_code(commodity_code)
    validate_market_year(market_year)
    if country_code is not None:
        validate_country_code(country_code)
    request: dict[str, str | int | None] = {
        "commodity_code": commodity_code,
        "market_year": market_year,
        "country_code": country_code,
    }
    try:
        if country_code is None:
            endpoint = "PSDData_GetCommodityDataByYear"
            records = await api.PSDData_GetCommodityDataByYear(commodity_code, market_year)
        else:
            endpoint = "PSDData_GetCountryCommodityDataByYear"
            records = await api.PSDData_GetCountryCommodityDataByYear(
                commodity_code, country_code, market_year
            )
    except NotFoundError as exc:
        country = "every country" if country_code is None else f"country {country_code}"
        raise _absent(exc, commodity_code, country, market_year) from exc
    meta = ResultMeta(source=SOURCE, endpoint=endpoint, vintage=_vintage(records), request=request)
    return Result(data=records, meta=meta)


async def get_world_data_async(
    commodity_code: str, market_year: int
) -> Result[list[CommodityData]]:
    """PSD supply and distribution forecasts for one commodity and market year, world total.

    One record per attribute, aggregated by PSD over every applicable country
    (``country_code`` ``"00"``). ``attribute_id`` and ``unit_id`` are PSD's integer ids,
    which ``enums.AttributeId`` and ``enums.UnitId`` name; ``value`` is in that unit.
    ``meta.vintage`` is the PSD release that last revised the figures, as upstream names
    it (``"2026-10"``), the latest release of any country for this commodity and market
    year; ``meta.published_at`` stays empty, since PSD gives no day. The code and the
    year are checked before any call; a market year without data raises
    ``NotFoundError``.

    Args:
        commodity_code: PSD commodity code, seven digits, e.g. ``"0410000"`` (Wheat),
            ``"0440000"`` (Corn), ``"2222000"`` (Oilseed, Soybean).
        market_year: PSD market year, e.g. ``2023``; data goes back to 1960 for most
            commodities.
    """
    validate_commodity_code(commodity_code)
    validate_market_year(market_year)
    request: dict[str, str | int | None] = {
        "commodity_code": commodity_code,
        "market_year": market_year,
    }
    try:
        records = await api.PSDData_GetWorldCommodityDataByYear(commodity_code, market_year)
    except NotFoundError as exc:
        raise _absent(exc, commodity_code, "the world", market_year) from exc
    meta = ResultMeta(
        source=SOURCE,
        endpoint="PSDData_GetWorldCommodityDataByYear",
        vintage=_vintage(records),
        request=request,
    )
    return Result(data=records, meta=meta)


async def get_release_dates_async(
    commodity_code: str, market_year: int | None = None, country_code: str | None = None
) -> Result[list[DataReleaseInfo]]:
    """When PSD last revised each country and market year of a commodity: poll for releases.

    One record per country and market year: ``release_year`` and ``release_month`` name
    the PSD release, a month without a day. Compare them with a stored ``meta.vintage``
    of ``get_data`` to fetch only what changed. Upstream answers every country and every
    market year since 1960 at once (7,754 records for wheat); ``market_year`` and
    ``country_code`` keep only the matching records, after the one call, and the MCP
    server returns at most 200 rows, so pass at least one of them there.

    Args:
        commodity_code: PSD commodity code, seven digits, e.g. ``"0410000"`` (Wheat),
            ``"0440000"`` (Corn), ``"2222000"`` (Oilseed, Soybean).
        market_year: Keep only this PSD market year, e.g. ``2023``; ``None`` keeps all.
        country_code: Keep only this PSD country code (not ISO), e.g. ``"US"``, ``"BR"``;
            ``None`` keeps all.
    """
    validate_commodity_code(commodity_code)
    if market_year is not None:
        validate_market_year(market_year)
    if country_code is not None:
        validate_country_code(country_code)
    releases = await api.PSDData_GetDataReleaseInfo(commodity_code)
    selected = [
        release
        for release in releases
        if (market_year is None or release.market_year == market_year)
        and (country_code is None or release.country_code == country_code)
    ]
    meta = ResultMeta(
        source=SOURCE,
        endpoint="PSDData_GetDataReleaseInfo",
        request={
            "commodity_code": commodity_code,
            "market_year": market_year,
            "country_code": country_code,
        },
    )
    return Result(data=selected, meta=meta)


def _packaged[M](name: str, kind: type[list[M]]) -> tuple[list[M], PackagedList]:
    """The packaged list ``name`` parsed into ``kind``, in upstream order, with its file."""
    packaged = packaged_values(name)
    if packaged is None:  # pragma: no cover - the five lists ship with the package
        raise KeyError(name)
    return parse(kind, packaged.records, source=SOURCE, endpoint=packaged.endpoint), packaged


def _packaged_meta(packaged: PackagedList, request: dict[str, str | None]) -> ResultMeta:
    """Answered now, from the list the package fetched on ``packaged.fetched``."""
    return ResultMeta(
        source=SOURCE,
        endpoint=packaged.endpoint,
        vintage=packaged.fetched.isoformat(),
        request=request,
    )


def _matches(search: str | None, *fields: str | int) -> bool:
    """Case-insensitive substring match of ``search`` in any of ``fields``; ``None`` matches."""
    if search is None:
        return True
    needle = search.casefold()
    return any(needle in str(field).casefold() for field in fields)


async def list_commodities_async(search: str | None = None) -> Result[list[Commodity]]:
    """List PSD's commodities with their codes, the values commodity_code takes.

    Answered from ``PSDData_GetCommodities`` as packaged with this version
    (``reference/commodities.json``), without an upstream call: 63 commodities when
    packaged, in upstream order, e.g. ``"0410000"`` Wheat, ``"0440000"`` Corn,
    ``"2222000"`` Oilseed, Soybean. ``meta.vintage`` is the day the package fetched the
    list (``"2026-10-23"``), ``meta.retrieved_at`` when this task answered.

    Args:
        search: Keep the commodities where this text occurs, ignoring case, in the code
            or the name, e.g. ``"wheat"`` (0410000 Wheat), ``"soybean"`` (meal, oil and
            oilseed, each also "(Local)"), ``"0440000"`` (Corn). Omit (``None``) for all.
    """
    commodities, packaged = _packaged("commodities", list[Commodity])
    selected = [c for c in commodities if _matches(search, c.commodity_code, c.commodity_name)]
    return Result(data=selected, meta=_packaged_meta(packaged, {"search": search}))


async def list_countries_async(
    region_code: str | None = None, search: str | None = None
) -> Result[list[Country]]:
    """List PSD's countries with their codes and regions, the values country_code takes.

    Answered from ``PSDData_GetCountries`` as packaged with this version
    (``reference/countries.json``), without an upstream call: 251 countries when
    packaged, in upstream order, each with its PSD region (``list_regions``) and its GENC
    code where upstream has one. Codes are PSD's own, not ISO: ``"US"`` United States,
    ``"BR"`` Brazil, ``"CH"`` China, ``"E4"`` European Union; aggregates such as ``"T3"``
    Africa, NEC have no GENC code. The MCP server returns at most 200 rows per call,
    which cuts this list after Somalia, before the United States, so pass
    ``region_code`` (the largest, ``"R11"`` Sub-Saharan Africa, has 57 countries) or
    ``search`` there to see the rest; Python and HTTP results are whole.
    ``meta.vintage`` is the day the package fetched the list (``"2026-10-23"``),
    ``meta.retrieved_at`` when this task answered.

    Args:
        region_code: Keep the countries of this PSD region, spelled exactly as
            ``list_regions`` spells it, e.g. ``"R01"`` (North America, 5 countries),
            ``"R05"`` (European Union), ``"R11"`` (Sub-Saharan Africa). ``"R15"`` holds
            four countries (Africa, NEC; Fernando Po; French Equatorial Africa; Other)
            although ``list_regions`` lacks it. A code no country carries yields an
            empty list. Omit (``None``) for every region.
        search: Keep the countries where this text occurs, ignoring case, in the code or
            the name, e.g. ``"united"`` (TC United Arab Emirates, UK United Kingdom, US
            United States), ``"E4"``, ``"brazil"``. Omit (``None``) for every country.
    """
    countries, packaged = _packaged("countries", list[Country])
    selected = [
        c
        for c in countries
        if (region_code is None or c.region_code == region_code)
        and _matches(search, c.country_code, c.country_name)
    ]
    request = {"region_code": region_code, "search": search}
    return Result(data=selected, meta=_packaged_meta(packaged, request))


async def list_regions_async() -> Result[list[Region]]:
    """List PSD's regions with their codes, the values region_code of list_countries takes.

    Answered from ``PSDData_GetRegions`` as packaged with this version
    (``reference/regions.json``), without an upstream call: 15 regions when packaged, in
    upstream order, from ``"R00"`` World and ``"R01"`` North America to ``"R18"`` East
    Asia. Upstream's list lacks ``"R15"``, the region of four countries in
    ``list_countries`` (Africa, NEC and three more); it is kept as upstream sends it.
    ``meta.vintage`` is the day the package fetched the list (``"2026-10-23"``),
    ``meta.retrieved_at`` when this task answered.
    """
    regions, packaged = _packaged("regions", list[Region])
    return Result(data=regions, meta=_packaged_meta(packaged, {}))


async def list_units_of_measure_async() -> Result[list[UnitOfMeasure]]:
    """List PSD's units of measure with their ids, the unit_id of every data record.

    Answered from ``PSDData_GetUnitsOfMeasure`` as packaged with this version
    (``reference/unitsOfMeasure.json``), without an upstream call: 42 units when
    packaged, in upstream order, e.g. ``8`` (1000 MT), ``4`` (1000 HA), ``26`` (MT/HA).
    Descriptions are upstream's, padded with spaces to 20 characters
    (``"(1000 MT)           "``). ``enums.UnitId`` names the same ids. ``meta.vintage``
    is the day the package fetched the list (``"2026-10-23"``), ``meta.retrieved_at``
    when this task answered.
    """
    units, packaged = _packaged("unitsOfMeasure", list[UnitOfMeasure])
    return Result(data=units, meta=_packaged_meta(packaged, {}))


async def list_commodity_attributes_async(
    search: str | None = None,
) -> Result[list[CommodityAttribute]]:
    """List PSD's commodity attributes with their ids, the attribute_id of every data record.

    Answered from ``PSDData_GetCommodityAttributes`` as packaged with this version
    (``reference/commodityAttributes.json``), without an upstream call: 85 attributes
    when packaged, in upstream order, e.g. ``28`` Production, ``57`` Imports, ``88``
    Exports, ``176`` Ending Stocks. Names are not unique: ``"Total Disappearance"`` is
    126 and 173, ``"Fresh Dom. Consumption"`` 133 and 135; the id tells them apart.
    ``enums.AttributeId`` names the same ids. ``meta.vintage`` is the day the package
    fetched the list (``"2026-10-23"``), ``meta.retrieved_at`` when this task answered.

    Args:
        search: Keep the attributes where this text occurs, ignoring case, in the id
            (as digits) or the name, e.g. ``"stocks"``, ``"disappearance"`` (126 and 173
            Total Disappearance, 151 Other Disappearance), ``"28"`` (28 Production, and
            128 Dom. Leaf Consumption: the id matches as text). Omit (``None``) for all.
    """
    attributes, packaged = _packaged("commodityAttributes", list[CommodityAttribute])
    selected = [a for a in attributes if _matches(search, a.attribute_id, a.attribute_name)]
    return Result(data=selected, meta=_packaged_meta(packaged, {"search": search}))


get_data = sync(get_data_async)
get_world_data = sync(get_world_data_async)
get_release_dates = sync(get_release_dates_async)
list_commodities = sync(list_commodities_async)
list_countries = sync(list_countries_async)
list_regions = sync(list_regions_async)
list_units_of_measure = sync(list_units_of_measure_async)
list_commodity_attributes = sync(list_commodity_attributes_async)
