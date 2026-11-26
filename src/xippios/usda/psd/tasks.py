"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.

``meta.vintage`` of the data tasks is the PSD release that last revised the result, as
upstream names it: the latest ``calendarYear``-``month`` across the records, zero-padded
(``"2026-07"``). Every record carries the release that last revised it; for one country
all records share one, for every country and the world the latest is taken. In every
case recorded with its whole release list (wheat 2023: US, all countries, world, in the
whole answers recorded on 2026-10-23, commit ``07b88ad``) this equals
``PSDData_GetDataReleaseInfo``'s record for the same commodity, market year and country
(or the latest across countries), so no extra call is needed; the corn and soybeans
recordings are internally consistent. ``meta.published_at`` stays ``None`` for every
task: PSD gives a month, no day, and the first of the month would predate the real
mid-month release, a look-ahead bias in an as-of store. ``get_release_dates`` is the way
to poll for new releases.

The ``list_*`` tasks answer from the five lists packaged under ``reference/`` and make no
upstream call. Core's ``PackagedList`` reads the file and builds ``meta``
(sdk-core ADR-0041, decision 1): ``meta.endpoint`` is the operation the list was fetched
from (``"PSDData_GetCountries"``), ``meta.retrieved_at`` is when the package fetched the list,
the file's ``fetched``, a UTC time to the second (``2026-10-28T21:42:03Z``), and
``meta.vintage`` is ``None``: upstream gives these lists no release identifier, and a
fetch date is not one. Their filters (``search``, ``region_code``) only select records of
the packaged list, which keep upstream's order and values; ``meta.request`` carries those
given, and ``search`` is a case-insensitive substring match (``xippios.core.matches``).

A ranking, a pivot and a selection of the newest release are no task of a source package
(conventions §14; sdk-core ADR-0060): a caller reads those records from ``get_data`` and
``get_release_dates``. ``get_time_series`` puts together and orders the records of the
request ``get_data`` makes for one country, once per market year, conventions §4's period
series: no record is changed, nothing is derived, converted, filled or renamed (sdk-core
ADR-0028).
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from xippios.core import (
    InvalidRequestError,
    PackagedList,
    Result,
    ResultCap,
    ResultMeta,
    matches,
    names_codes,
    sync,
)
from xippios.usda.fas import NoDataForYear

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
    ATTRIBUTES,
    COMMODITIES,
    COUNTRIES,
    PACKAGE,
    validate_attribute_id,
    validate_commodity_code,
    validate_country_code,
    validate_market_year,
    validate_region_code,
    validate_since,
)

__all__ = [
    "get_data",
    "get_release_dates",
    "get_time_series",
    "get_world_data",
    "list_commodities",
    "list_commodity_attributes",
    "list_countries",
    "list_regions",
    "list_units_of_measure",
]

MCP_INSTRUCTIONS = (
    "USDA FAS PSD Online via xippios. "
    "Tools are read-only. "
    "Where list tools (usda_psd_list_*) exist, call them first to find valid values, "
    "then query."
)
"""The read server's instructions for agents, which core's tool set reads from this module
(conventions §8; sdk-core ADR-0063, decision 7)."""

# A task named here is Python-only: no tool, no route; the adapters skip it (sdk-core ADR-0040,
# decision 4).
BULK_TASKS: frozenset[str] = frozenset()

MCP_CAPS: Mapping[str, ResultCap] = {
    "list_countries": ResultCap(max_rows=300),
    "get_data": ResultCap(note="filter by country_code to see the rest"),
    "get_release_dates": ResultCap(
        note="filter by market_year, country_code or since to see the rest"
    ),
    "get_time_series": ResultCap(
        note="filter by attribute_id or narrow start_year and end_year to see the rest"
    ),
}
"""MCP result caps of their own, by task function name (conventions §8, sdk-core ADR-0038).

``list_countries`` is a reference list an agent needs whole: 251 countries when packaged,
past the family's default of 200 rows, and 22,467 bytes of compact JSON, well within its
64 KB. ``get_data``, ``get_release_dates`` and ``get_time_series`` keep the family's
limits, 200 rows or 64 KB (``ResultCap``'s defaults), with a note naming their filters, so
a cut answer tells the agent how to narrow it: every country at once is up to about 1,900
rows, wheat's release list 7,754, a series of every attribute 15 rows a year for wheat in
the United States. Every other tool keeps the default with core's note.
"""


SERIES_START = 1960
"""First market year ``get_time_series`` asks for: the snapshot's summary of the data
operations says "PSD Database has data for most commodities since year 1960"."""

SERIES_MAX_YEARS = 100
"""Most market years one ``get_time_series`` call spans, a self-imposed sanity bound:
1960 to the current forecast years is about 67 requests, 1960 to 9999 would be 8,040."""


def _vintage(records: list[CommodityData]) -> str | None:
    """The latest ``calendarYear``-``month`` across ``records``, zero-padded; ``None`` if empty."""
    if not records:
        return None
    year, month = max((record.calendar_year, record.month) for record in records)
    return f"{year:04d}-{month:02d}"


def _absent(
    exc: NoDataForYear, commodity_code: str, country: str, market_year: int
) -> NoDataForYear:
    """PSD's empty 404 again, naming what was asked for, in the source's name.

    Only ``NoDataForYear``, the shared package's class that the gateway returns on a data
    path, means "no data for this market year"; any other ``NotFoundError`` (the gateway's
    ``NOT_FOUND``) is not caught and propagates as is.
    """
    return NoDataForYear(
        exc.path,
        f"PSD has no data for commodity {commodity_code}, {country}, market year "
        f"{market_year}: upstream answered HTTP 404 ({exc.message}). PSD has data for most "
        "commodities since 1960.",
        source=exc.source,
    )


@names_codes(commodity_code=COMMODITIES, country_code=COUNTRIES)
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
    ``NotFoundError``. Every country is up to about 1,900 rows (1,875 for corn in 2023).

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
            answer = await api.get_commodity_data_by_year(commodity_code, market_year)
        else:
            endpoint = "PSDData_GetCountryCommodityDataByYear"
            answer = await api.get_country_commodity_data_by_year(
                commodity_code, country_code, market_year
            )
    except NoDataForYear as exc:
        country = "every country" if country_code is None else f"country {country_code}"
        raise _absent(exc, commodity_code, country, market_year) from exc
    records = answer.payload
    meta = ResultMeta(
        source=SOURCE,
        endpoint=endpoint,
        retrieved_at=answer.retrieved_at,
        vintage=_vintage(records),
        request=request,
    )
    return Result(data=records, meta=meta)


@names_codes(commodity_code=COMMODITIES)
async def get_world_data_async(
    commodity_code: str, market_year: int
) -> Result[list[CommodityData]]:
    """PSD supply and distribution forecasts for one commodity and market year, world total.

    One record per attribute, aggregated by PSD over every applicable country
    (``country_code`` ``"00"``). ``attribute_id`` and ``unit_id`` are PSD's integer ids,
    which ``enums.AttributeId`` and ``enums.UnitId`` name; ``value`` is in that unit.
    ``meta.vintage`` is the PSD release that last revised the figures, as upstream names
    it (``"2026-10"``), the latest release of any country for this commodity and market
    year (in the whole answers recorded on 2026-10-23, commit ``07b88ad``);
    ``meta.published_at`` stays empty, since PSD gives no day. The code and the
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
        answer = await api.get_world_commodity_data_by_year(commodity_code, market_year)
    except NoDataForYear as exc:
        raise _absent(exc, commodity_code, "the world", market_year) from exc
    records = answer.payload
    meta = ResultMeta(
        source=SOURCE,
        endpoint="PSDData_GetWorldCommodityDataByYear",
        retrieved_at=answer.retrieved_at,
        vintage=_vintage(records),
        request=request,
    )
    return Result(data=records, meta=meta)


def _release(record: DataReleaseInfo) -> tuple[int, int]:
    """A release record's ``(release_year, release_month)``, comparable with ``since``."""
    return record.release_year, record.release_month


@names_codes(commodity_code=COMMODITIES, country_code=COUNTRIES)
async def get_release_dates_async(
    commodity_code: str,
    market_year: int | None = None,
    country_code: str | None = None,
    since: str | None = None,
) -> Result[list[DataReleaseInfo]]:
    """When PSD last revised each country and market year of a commodity: poll for releases.

    One record per country and market year: ``release_year`` and ``release_month`` name
    the PSD release, a month without a day. Compare them with a stored ``meta.vintage``
    of ``get_data``, or pass that vintage as ``since``, to fetch only what changed.
    Upstream answers every country and every market year since 1960 at once (7,754
    records for wheat), ordered by market year; ``market_year``, ``country_code`` and
    ``since`` keep only the matching records, after the one call, in upstream's order.

    Args:
        commodity_code: PSD commodity code, seven digits, e.g. ``"0410000"`` (Wheat),
            ``"0440000"`` (Corn), ``"2222000"`` (Oilseed, Soybean).
        market_year: Keep only this PSD market year, e.g. ``2023``; ``None`` keeps all.
        country_code: Keep only this PSD country code (not ISO), e.g. ``"US"``, ``"BR"``;
            ``None`` keeps all.
        since: Keep only the records revised in a release later than this month,
            ``"YYYY-MM"``, e.g. ``"2026-09"``; the form ``meta.vintage`` takes, so a
            stored vintage passes as it is, and that release itself is not kept (strictly
            after). ``None`` keeps all.
    """
    validate_commodity_code(commodity_code)
    if market_year is not None:
        validate_market_year(market_year)
    if country_code is not None:
        validate_country_code(country_code)
    after = None if since is None else validate_since(since)
    answer = await api.get_data_release_info(commodity_code)
    selected = [
        release
        for release in answer.payload
        if (market_year is None or release.market_year == market_year)
        and (country_code is None or release.country_code == country_code)
        and (after is None or _release(release) > after)
    ]
    meta = ResultMeta(
        source=SOURCE,
        endpoint="PSDData_GetDataReleaseInfo",
        retrieved_at=answer.retrieved_at,
        request={
            "commodity_code": commodity_code,
            "market_year": market_year,
            "country_code": country_code,
            "since": since,
        },
    )
    return Result(data=selected, meta=meta)


def _attribute_ids(attribute_id: object) -> frozenset[int] | None:
    """The ids ``get_time_series`` keeps, checked by one call; ``None`` keeps every attribute.

    An id or a sequence of ids, checked as one list by ``validate_attribute_id``, core's
    ``check``, which refuses the first id it refuses and an empty list; text is no sequence of
    ids here, so ``"28"`` is refused as not an integer, naming the integer to pass.

    Raises:
        InvalidRequestError: An empty sequence, or a value that is not an integer id.
        UnknownCode: An id the packaged list lacks, naming the closest.
    """
    if attribute_id is None:
        return None
    ids: list[Any]
    if isinstance(attribute_id, Sequence) and not isinstance(attribute_id, str | bytes):
        ids = list(attribute_id)
    else:
        ids = [attribute_id]
    return frozenset(validate_attribute_id(ids))


@names_codes(commodity_code=COMMODITIES, country_code=COUNTRIES, attribute_id=ATTRIBUTES)
async def get_time_series_async(
    commodity_code: str,
    country_code: str,
    start_year: int,
    end_year: int,
    attribute_id: int | Sequence[int] | None = None,
) -> Result[list[CommodityData]]:
    """One country's PSD figures for a commodity over a range of market years.

    One request to ``PSDData_GetCountryCommodityDataByYear`` per market year, oldest
    first, at the client's pace of one request per second, and each counts against
    api.data.gov's quota of 1,000 requests per hour per key: 2021 to 2023 is three
    requests and about three seconds, 1960 to 2026 sixty-seven, so ask for the years you
    need; a range of more than 100 market years is refused. Of each answer the records
    of the attributes asked for, or all of them when ``attribute_id`` is omitted, are
    kept exactly as upstream sent them, ordered by market year and within a year in
    upstream's order: ``value`` is in its ``unit_id``, and ``calendar_year`` and
    ``month`` name the release that last revised that year, which may differ from year
    to year. A market year PSD has no data for (its empty HTTP 404, recorded for 1900),
    or whose answer has no record for the attributes, is absent from the list: no gap is
    filled, nothing interpolated, no error raised; a range without any record is an
    empty list. A year beyond PSD's forecasts is expected to answer the same 404 (not
    recorded) and still costs its request. Any other error, the gateway's own 404
    included, is raised. ``meta.vintage`` is the latest release across the records
    (``"2026-07"``); ``meta.published_at`` stays empty. Codes, every attribute id, both
    years and the range are checked before the first request.

    Args:
        commodity_code: PSD commodity code, seven digits, e.g. ``"0410000"`` (Wheat),
            ``"0440000"`` (Corn), ``"2222000"`` (Oilseed, Soybean).
        country_code: PSD country code (not ISO), e.g. ``"US"`` (United States), ``"BR"``
            (Brazil), ``"E4"`` (European Union).
        start_year: First PSD market year, 1960 or later (PSD: "PSD Database has data
            for most commodities since year 1960"), e.g. ``2021``.
        end_year: Last PSD market year, included, e.g. ``2023``; not before
            ``start_year`` and at most 99 years after it. No other bound.
        attribute_id: PSD attribute id, or a list of them, e.g. ``28`` (Production),
            ``[28, 88]`` (Production and Exports), ``176`` (Ending Stocks);
            ``list_commodity_attributes`` lists them. Omit it (``None``) for every
            attribute of each answer, 15 a year for wheat in the United States. An empty
            list is refused.
    """
    validate_commodity_code(commodity_code)
    validate_country_code(country_code)
    attribute_ids = _attribute_ids(attribute_id)
    validate_market_year(start_year)
    validate_market_year(end_year)
    if start_year < SERIES_START:
        raise InvalidRequestError(
            f"start_year must be {SERIES_START} or later, got {start_year}. Nothing was sent. "
            'The PSD API documentation says "PSD Database has data for most commodities since '
            f'year 1960", so each year before it would spend a request on a 404.',
            source=SOURCE,
        )
    if start_year > end_year:
        raise InvalidRequestError(
            f"start_year {start_year} is after end_year {end_year}. Nothing was sent. Pass the "
            "earlier market year first, e.g. start_year=2021, end_year=2023.",
            source=SOURCE,
        )
    if end_year - start_year + 1 > SERIES_MAX_YEARS:
        raise InvalidRequestError(
            f"{start_year} to {end_year} is {end_year - start_year + 1} market years, one "
            f"request each; a series spans at most {SERIES_MAX_YEARS}. PSD's data starts in "
            "1960 and reaches the current forecast year, so narrow the range.",
            source=SOURCE,
        )
    request: dict[str, Any] = {
        "commodity_code": commodity_code,
        "country_code": country_code,
        "start_year": start_year,
        "end_year": end_year,
        "attribute_id": list(attribute_id) if isinstance(attribute_id, Sequence) else attribute_id,
    }
    series: list[CommodityData] = []
    retrieved: list[datetime] = []
    for market_year in range(start_year, end_year + 1):
        try:
            answer = await api.get_country_commodity_data_by_year(
                commodity_code, country_code, market_year
            )
        except NoDataForYear:
            continue  # PSD's empty 404: no data for this market year, the year is absent
        retrieved.append(answer.retrieved_at)
        series.extend(
            record
            for record in answer.payload
            if attribute_ids is None or record.attribute_id in attribute_ids
        )
    meta = ResultMeta(
        source=SOURCE,
        endpoint="PSDData_GetCountryCommodityDataByYear",
        # the oldest answer assembled; now where every year answered PSD's empty 404 (§4)
        retrieved_at=min(retrieved, default=datetime.now(UTC)),
        vintage=_vintage(series),
        request=request,
    )
    return Result(data=series, meta=meta)


async def list_commodities_async(search: str | None = None) -> Result[list[Commodity]]:
    """List PSD's commodities with their codes, the values commodity_code takes.

    Answered from ``PSDData_GetCommodities`` as packaged with this version
    (``reference/commodities.json``), without an upstream call: 63 commodities when
    packaged, in upstream order, e.g. ``"0410000"`` Wheat, ``"0440000"`` Corn,
    ``"2222000"`` Oilseed, Soybean. ``meta.retrieved_at`` is when the package fetched the
    list (2026-10-28, UTC); ``meta.vintage`` is empty, as upstream gives the list no
    release identifier.

    Args:
        search: Keep the commodities where this text occurs, ignoring case, in the code
            or the name, e.g. ``"wheat"`` (0410000 Wheat), ``"soybean"`` (meal, oil and
            oilseed, each also "(Local)"), ``"0440000"`` (Corn). Omit (``None``) for all.
    """
    packaged = PackagedList.load(PACKAGE, "commodities")
    commodities = packaged.parse(Commodity, source=SOURCE)
    selected = [c for c in commodities if matches(search, c.commodity_code, c.commodity_name)]
    return Result(data=selected, meta=packaged.meta(SOURCE, request={"search": search}))


async def list_countries_async(
    region_code: str | None = None, search: str | None = None
) -> Result[list[Country]]:
    """List PSD's countries with their codes and regions, the values country_code takes.

    Answered from ``PSDData_GetCountries`` as packaged with this version
    (``reference/countries.json``), without an upstream call: 251 countries when
    packaged, in upstream order, each with its PSD region (``list_regions``) and its GENC
    code where upstream has one. Codes are PSD's own, not ISO: ``"US"`` United States,
    ``"BR"`` Brazil, ``"CH"`` China, ``"E4"`` European Union; aggregates such as ``"T3"``
    Africa, NEC have no GENC code. ``meta.retrieved_at`` is when the package fetched the
    list (2026-10-28, UTC); ``meta.vintage`` is empty, as upstream gives the list no
    release identifier.

    Args:
        region_code: Keep the countries of this PSD region, spelled exactly as
            ``list_regions`` spells it, e.g. ``"R01"`` (North America, 5 countries),
            ``"R05"`` (European Union), ``"R11"`` (Sub-Saharan Africa). ``"R15"`` holds
            four countries (Africa, NEC; Fernando Po; French Equatorial Africa; Other)
            although ``list_regions`` lacks it. A code no packaged country carries is
            refused, naming the closest; ``"R00"`` (World) is one, and the world total is
            ``get_world_data``'s. Omit (``None``) for every region.
        search: Keep the countries where this text occurs, ignoring case, in the code,
            the name or the GENC code, e.g. ``"united"`` (TC United Arab Emirates, UK
            United Kingdom, US United States), ``"USA"`` (US United States, by its GENC
            code), ``"E4"``, ``"brazil"``. Omit (``None``) for every country.
    """
    if region_code is not None:
        validate_region_code(region_code)
    packaged = PackagedList.load(PACKAGE, "countries")
    countries = packaged.parse(Country, source=SOURCE)
    selected = [
        c
        for c in countries
        if (region_code is None or c.region_code == region_code)
        and matches(search, c.country_code, c.country_name, c.genc_code)
    ]
    request = {"region_code": region_code, "search": search}
    return Result(data=selected, meta=packaged.meta(SOURCE, request=request))


async def list_regions_async() -> Result[list[Region]]:
    """List PSD's regions with their codes, the values region_code of list_countries takes.

    Answered from ``PSDData_GetRegions`` as packaged with this version
    (``reference/regions.json``), without an upstream call: 15 regions when packaged, in
    upstream order, from ``"R00"`` World and ``"R01"`` North America to ``"R18"`` East
    Asia. Upstream's list lacks ``"R15"``, the region of four countries in
    ``list_countries`` (Africa, NEC and three more); it is kept as upstream sends it.
    ``meta.retrieved_at`` is when the package fetched the list (2026-10-28, UTC);
    ``meta.vintage`` is empty, as upstream gives the list no release identifier.
    """
    packaged = PackagedList.load(PACKAGE, "regions")
    return Result(data=packaged.parse(Region, source=SOURCE), meta=packaged.meta(SOURCE))


async def list_units_of_measure_async() -> Result[list[UnitOfMeasure]]:
    """List PSD's units of measure with their ids, the unit_id of every data record.

    Answered from ``PSDData_GetUnitsOfMeasure`` as packaged with this version
    (``reference/unitsOfMeasure.json``), without an upstream call: 42 units when
    packaged, in upstream order, e.g. ``8`` (1000 MT), ``4`` (1000 HA), ``26`` (MT/HA).
    Descriptions are upstream's, padded with spaces to 20 characters
    (``"(1000 MT)           "``). ``enums.UnitId`` names the same ids.
    ``meta.retrieved_at`` is when the package fetched the list (2026-10-28, UTC);
    ``meta.vintage`` is empty, as upstream gives the list no release identifier.
    """
    packaged = PackagedList.load(PACKAGE, "unitsOfMeasure")
    return Result(data=packaged.parse(UnitOfMeasure, source=SOURCE), meta=packaged.meta(SOURCE))


async def list_commodity_attributes_async(
    search: str | None = None,
) -> Result[list[CommodityAttribute]]:
    """List PSD's commodity attributes with their ids, the attribute_id of every data record.

    Answered from ``PSDData_GetCommodityAttributes`` as packaged with this version
    (``reference/commodityAttributes.json``), without an upstream call: 85 attributes
    when packaged, in upstream order, e.g. ``28`` Production, ``57`` Imports, ``88``
    Exports, ``176`` Ending Stocks. Names are not unique: ``"Total Disappearance"`` is
    126 and 173, ``"Fresh Dom. Consumption"`` 133 and 135; the id tells them apart.
    ``enums.AttributeId`` names the same ids. ``meta.retrieved_at`` is when the package
    fetched the list (2026-10-28, UTC); ``meta.vintage`` is empty, as upstream gives the
    list no release identifier.

    Args:
        search: Keep the attributes where this text occurs, ignoring case, in the id
            (as digits) or the name, e.g. ``"stocks"``, ``"disappearance"`` (126 and 173
            Total Disappearance, 151 Other Disappearance), ``"28"`` (28 Production, and
            128 Dom. Leaf Consumption: the id matches as text). Omit (``None``) for all.
    """
    packaged = PackagedList.load(PACKAGE, "commodityAttributes")
    attributes = packaged.parse(CommodityAttribute, source=SOURCE)
    selected = [a for a in attributes if matches(search, a.attribute_id, a.attribute_name)]
    return Result(data=selected, meta=packaged.meta(SOURCE, request={"search": search}))


get_data = sync(get_data_async)
get_world_data = sync(get_world_data_async)
get_release_dates = sync(get_release_dates_async)
get_time_series = sync(get_time_series_async)
list_commodities = sync(list_commodities_async)
list_countries = sync(list_countries_async)
list_regions = sync(list_regions_async)
list_units_of_measure = sync(list_units_of_measure_async)
list_commodity_attributes = sync(list_commodity_attributes_async)
