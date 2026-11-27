"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.

``meta.vintage`` of the data tasks is the PSD release that last revised the result, as
upstream names it: the latest ``calendarYear``-``month`` across the records, zero-padded
(``"2026-07"``). Every record carries the release that last revised it; for one country
all records share one, for every country and the world the latest is taken. This equals
``PSDData_GetDataReleaseInfo``'s record for the same commodity, market year and country, or
the latest across countries, as the note "A data record names the release that last
revised it" of ``docs/upstream/OBSERVED.md`` shows, so no extra call is needed.
``meta.published_at`` stays ``None`` for every
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
    Answer,
    Ceiling,
    InvalidRequestError,
    PackagedList,
    Result,
    ResultCap,
    ResultMeta,
    fetch_periods,
    matches,
    names_codes,
    newer_than,
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
    _CARRIED_REGIONS,
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
    "get_data": ResultCap(note="pass country_code, e.g. US, for one country's rows", paged=True),
    "get_release_dates": ResultCap(
        note="pass market_year, country_code or since to narrow the list", paged=True
    ),
    "get_time_series": ResultCap(
        note=(
            "the newest market years are shown; pass attribute_id or narrow start_year and "
            "end_year to see the rest. One call sends one request per market year, at most 24 "
            "requests and 96 attempts with retries unless --series-years sets another ceiling"
        ),
        keep="last",
    ),
}
"""MCP result caps of their own, by task function name (conventions §8, sdk-core ADR-0038).

``list_countries`` is a reference list an agent needs whole: 251 countries when packaged,
past the family's default of 200 rows, and 22,467 bytes of compact JSON, well within its
64 KB. ``get_data``, ``get_release_dates`` and ``get_time_series`` keep the family's
limits, 200 rows or 64 KB (``ResultCap``'s defaults), with a note naming their filters, so
a cut answer tells the agent how to narrow it: every country at once is up to about 1,900
rows, wheat's release list 7,754, a series of every attribute 15 rows a year for wheat in
the United States. ``get_data`` and ``get_release_dates`` are one request each, which core's
response cache keeps for its lifetime, so their caps are paged: the tool's ``offset``
continues a cut answer by running the task again, which the cache answers, and costs upstream
nothing (conventions §8; sdk-core ADR-0061, decision 9). The largest, wheat's release list of
837,433 bytes, lies under the cache's bound of a body, 8 MiB. ``get_time_series``' cap keeps
the last rows, the newest market years of a series ordered oldest first, and is not paged,
since a series of more market years than the cache holds would send its requests again; its
note states the most that one call sends on the MCP server, with core's four attempts for
each request (sdk-core ADR-0061, decision 8). Every other tool keeps the default with core's
note.
"""


SERIES_START = 1960
"""First market year ``get_time_series`` asks for: the snapshot's summary of the data
operations says "PSD Database has data for most commodities since year 1960" (the
maintainer's decision of 2026-11-26 keeps it)."""

SERIES = Ceiling(
    100,
    unit="market years",
    mcp=24,
    option="--series-years",
    help="one request per market year, so 24 market years send 24 requests, 96 attempts",
    source=SOURCE,
)
"""Most market years one ``get_time_series`` call spans, ends included, core's ``Ceiling``
(conventions §4; sdk-core ADR-0054, ADR-0061, decision 8): 100 in Python and over HTTP, and
24 on the MCP server, which its option ``--series-years`` sets from 1 to 100, the one form of
a ceiling that the sources share, its option named after its unit (the maintainer's decision
of 2026-11-26). One request per market year, at the client's pace of one a second, of the
1,000 an hour that the api.data.gov key shares with every package that uses it: 1960 to the
current forecast year is about 67 requests. One call sends at most 100 requests, 400 attempts
with core's four for each, and 24 and 96 on the MCP server; a longer range is refused before
the first request."""

mcp_add_options = SERIES.add_options
"""The MCP server's option ``--series-years``, a hook that core's tool set reads."""
mcp_apply_options = SERIES.apply_options
"""Sets ``SERIES`` from ``--series-years`` for the process, a hook that core's tool set reads."""


def _vintage(records: list[CommodityData]) -> str | None:
    """The latest ``calendarYear``-``month`` across ``records``, zero-padded; ``None`` if empty."""
    if not records:
        return None
    year, month = max((record.calendar_year, record.month) for record in records)
    return f"{year:04d}-{month:02d}"


def _no_data(exc: NoDataForYear) -> str:
    """The note of an empty answer for PSD's empty 404, which names the request it answered.

    Only ``NoDataForYear``, the shared package's class that the gateway returns on a data path,
    means "no data for this market year", so the task answers the empty list with this note
    and sends no second request (https://github.com/xippios/sdk-usda-esr/issues/88, the
    maintainer's decision of 2026-11-26); any other ``NotFoundError`` (the gateway's
    ``NOT_FOUND``) is not caught and propagates as is. PSD answers market year 1900 so
    (recorded); a market year it has not released is expected to answer alike, not recorded.
    The note names the task it points to and its MCP tool, since an agent calls the tool, as a
    refusal does (conventions §8).
    """
    return (
        f"PSD answered GET {exc.path} with HTTP 404 and an empty body, its answer for a market "
        "year it holds no data for, which a market year it has not released is expected to "
        "answer alike; get_release_dates (over MCP, the tool usda_psd_get_release_dates) names "
        "the market years that hold data."
    )


@names_codes(commodity_code=COMMODITIES, country_code=COUNTRIES)
async def get_data_async(
    commodity_code: str, market_year: int, *, country_code: str | None = None
) -> Result[list[CommodityData]]:
    """PSD supply and distribution forecasts for one commodity and market year, by country.

    One record per country and attribute (area, production, imports, exports,
    consumption, stocks, ...): ``attribute_id`` and ``unit_id`` are PSD's integer ids,
    which ``enums.AttributeId`` and ``enums.UnitId`` name; ``value`` is in that unit.
    Codes and the year are checked before any request, an unknown code refused naming the
    closest ones. Each record's
    ``calendar_year`` and ``month`` name the PSD release that last revised it;
    ``meta.vintage`` is the latest of them (``"2026-07"``), empty where no record names one,
    and ``meta.published_at`` stays empty, since PSD gives no day. An empty list means PSD
    holds no records for that combination; a market year PSD holds no data for, or has not
    released, answers the empty list with a note, and ``get_release_dates`` names the market
    years that hold data.
    Every country at once is up to about 1,900 rows.

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
        empty = ResultMeta(source=SOURCE, endpoint=endpoint, request=request, notes=[_no_data(exc)])
        return Result(data=[], meta=empty)
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
    year, empty where no record names one; ``meta.published_at`` stays empty, since PSD
    gives no day. The world's ``"00"`` is no
    code of the packaged countries list, so a note says that ``meta.names`` leaves it out.
    The code and the year are checked before any request; a market year PSD holds no data
    for, or has not released, answers the empty list with a note, and ``get_release_dates``
    names the market years that hold data.

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
        empty = ResultMeta(
            source=SOURCE,
            endpoint="PSDData_GetWorldCommodityDataByYear",
            request=request,
            notes=[_no_data(exc)],
        )
        return Result(data=[], meta=empty)
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
    *,
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
    ``meta.vintage`` is the newest release of the whole list, ``"YYYY-MM"``, also where the
    filters keep no record, so the next poll passes it as ``since``; it is empty only where
    PSD lists no release for the commodity, since no record then names one.

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
    if since is not None:
        validate_since(since)  # refused before the request
    answer = await api.get_data_release_info(commodity_code)
    selected = [
        release
        for release in newer_than(since, answer.payload, released=_release, read=validate_since)
        if (market_year is None or release.market_year == market_year)
        and (country_code is None or release.country_code == country_code)
    ]
    newest = max((_release(release) for release in answer.payload), default=None)
    meta = ResultMeta(
        source=SOURCE,
        endpoint="PSDData_GetDataReleaseInfo",
        retrieved_at=answer.retrieved_at,
        # the newest release of the whole list, filtered or not, the marker of the next poll
        vintage=None if newest is None else f"{newest[0]:04d}-{newest[1]:02d}",
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


def _series_range(start_year: int, end_year: int) -> None:
    """Refuse a range that starts before 1960, runs backwards or spans more than ``SERIES``.

    Both years have passed ``validate_market_year``; the range is checked before the first
    request, as conventions §4 and §5 ask, with ``InvalidRequestError`` (sdk-core ADR-0007),
    each refusal saying that nothing was sent. The floor and the order are the task's own, and
    the ceiling core's ``Ceiling.check``, its advice naming the range to ask for (sdk-core
    ADR-0054).
    """
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
    most = SERIES.value
    SERIES.check(
        end_year - start_year + 1,
        asked=f"{start_year} to {end_year}",
        advice=(
            f"Narrow the range, e.g. start_year={end_year - most + 1}, end_year={end_year}, or "
            f"split it into calls of at most {most}."
        ),
    )


def _rows(count: int) -> str:
    return f"{count} row{'' if count == 1 else 's'}"


def _years_note(
    years: range,
    fetched: list[tuple[int, Answer[list[CommodityData]]]],
    kept: dict[int, int],
    attribute_ids: frozenset[int] | None,
) -> str:
    """The series' note on its market years: each answered with its rows, each passed over.

    A market year answered is named with its count of rows, in the order of the rows; one
    passed over is named for why: PSD's empty 404, a market year it holds no data for, or an
    answer without a record of the attributes asked for, or without any record where every
    attribute was asked for, e.g. ``"Market years in the order of the rows: 2021 with 1 row,
    2023 with 1 row; passed over, without data in PSD: 2022."``
    (https://github.com/xippios/sdk-usda-psd/issues/26; sdk-core ADR-0067, decision 1).
    """
    answered = [year for year, _ in fetched]
    with_rows = [f"{year} with {_rows(kept[year])}" for year in answered if kept[year]]
    no_record = [str(year) for year in answered if not kept[year]]
    no_data = [str(year) for year in years if year not in kept]
    asked = "a record of the attributes asked for" if attribute_ids is not None else "a record"
    parts = []
    if with_rows:
        parts.append(f"in the order of the rows: {', '.join(with_rows)}")
    if no_data:
        parts.append(f"passed over, without data in PSD: {', '.join(no_data)}")
    if no_record:
        parts.append(f"passed over, answered without {asked}: {', '.join(no_record)}")
    return f"Market years {'; '.join(parts)}."


@names_codes(commodity_code=COMMODITIES, country_code=COUNTRIES, attribute_id=ATTRIBUTES)
async def get_time_series_async(
    commodity_code: str,
    country_code: str,
    *,
    start_year: int,
    end_year: int,
    attribute_id: int | Sequence[int] | None = None,
) -> Result[list[CommodityData]]:
    """One country's PSD figures for a commodity over a range of market years, oldest first.

    One request to ``PSDData_GetCountryCommodityDataByYear`` per market year from
    ``start_year`` to ``end_year``, at the client's pace of one a second, each counted against
    api.data.gov's hourly quota: at most 100 market years in Python and over HTTP and 24 over
    MCP, unless ``--series-years`` sets another, so one call sends at most 100 requests, 400
    attempts with retries, and 24 and 96 over MCP. The records of the attributes asked for,
    or all, are kept as upstream sent them, by market year, then in upstream's order.
    ``meta.notes`` names each market year answered with its count of rows and each passed
    over, one PSD holds no data for or whose answer has no record kept; no gap is filled.
    Any other error stops the call and returns nothing. ``meta.vintage`` is the latest
    release of the records, empty where none is kept; ``meta.published_at`` stays empty.

    Args:
        commodity_code: PSD commodity code, seven digits, e.g. ``"0410000"`` (Wheat),
            ``"0440000"`` (Corn), ``"2222000"`` (Oilseed, Soybean).
        country_code: PSD country code (not ISO), e.g. ``"US"`` (United States), ``"BR"``
            (Brazil), ``"E4"`` (European Union).
        start_year: First PSD market year, 1960 or later (PSD: "PSD Database has data
            for most commodities since year 1960"), e.g. ``2021``; 1960 to the current
            forecast year is about 67 requests, so ask for the years you need.
        end_year: Last PSD market year, included, e.g. ``2023``; not before ``start_year``
            and within the ceiling: at most 99 years after it in Python and over HTTP, 23
            over MCP by default. A market year PSD has not released is expected to answer
            its empty 404, as 1900 does (an unreleased year is not recorded), and is passed
            over in ``meta.notes``, still costing its request.
        attribute_id: PSD attribute id, or a list of them, e.g. ``28`` (Production),
            ``[28, 88]`` (Production and Exports), ``176`` (Ending Stocks);
            ``list_commodity_attributes`` lists them. Omit it (``None``) for every
            attribute of each answer, 15 a year for wheat in the United States. An empty
            list is refused. Every id is checked before the first request. PSD's data
            operations take no attribute, so the package keeps the records of the ids asked
            for after each fetch.
    """
    validate_commodity_code(commodity_code)
    validate_country_code(country_code)
    attribute_ids = _attribute_ids(attribute_id)
    validate_market_year(start_year, name="start_year")
    validate_market_year(end_year, name="end_year")
    _series_range(start_year, end_year)
    request: dict[str, Any] = {
        "commodity_code": commodity_code,
        "country_code": country_code,
        "start_year": start_year,
        "end_year": end_year,
        "attribute_id": list(attribute_id) if isinstance(attribute_id, Sequence) else attribute_id,
    }
    # PSD's empty 404 is no data for that market year, which adds no rows; any other error
    # stops the series, naming the market years answered before it (sdk-core ADR-0054).
    years = range(start_year, end_year + 1)
    fetched = await fetch_periods(
        years,
        lambda market_year: api.get_country_commodity_data_by_year(
            commodity_code, country_code, market_year
        ),
        skip=(NoDataForYear,),
    )
    series: list[CommodityData] = []
    kept: dict[int, int] = {}
    for market_year, answer in fetched:
        rows = [
            r for r in answer.payload if attribute_ids is None or r.attribute_id in attribute_ids
        ]
        kept[market_year] = len(rows)
        series.extend(rows)
    meta = ResultMeta(
        source=SOURCE,
        endpoint="PSDData_GetCountryCommodityDataByYear",
        # the oldest answer assembled; now where every year answered PSD's empty 404 (§4)
        retrieved_at=min((answer.retrieved_at for _, answer in fetched), default=datetime.now(UTC)),
        vintage=_vintage(series),
        request=request,
        notes=[_years_note(years, fetched, kept, attribute_ids)],
    )
    return Result(data=series, meta=meta)


async def list_commodities_async(*, search: str | None = None) -> Result[list[Commodity]]:
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


@names_codes(region_code=_CARRIED_REGIONS)
async def list_countries_async(
    *, region_code: str | None = None, search: str | None = None
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
    *, search: str | None = None
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
