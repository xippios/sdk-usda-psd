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
recorded case this equals ``PSDData_GetDataReleaseInfo``'s record for the same
commodity, market year and country (or the latest across countries), so no extra call
is needed. ``meta.published_at`` stays ``None`` for every task: PSD gives a month, no
day, and the first of the month would predate the real mid-month release, a look-ahead
bias in an as-of store. ``get_release_dates`` is the way to poll for new releases.
"""

from xippios.core import NotFoundError, Result, ResultMeta, sync

from xippios.usda.psd import api
from xippios.usda.psd._client import SOURCE
from xippios.usda.psd.models import CommodityData, DataReleaseInfo
from xippios.usda.psd.params import (
    validate_commodity_code,
    validate_country_code,
    validate_market_year,
)

__all__ = ["get_data", "get_release_dates", "get_world_data"]


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


get_data = sync(get_data_async)
get_world_data = sync(get_world_data_async)
get_release_dates = sync(get_release_dates_async)
