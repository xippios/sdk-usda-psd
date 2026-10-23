"""Task-shaped functions for USDA FAS PSD Online.

The public API (ADR-0001, layer 2). A task composes endpoint wrappers from ``api/``,
resolves pagination and reference lookups, and returns ``Result[T]`` with full
``ResultMeta``. Write the async version, derive the sync one with ``xippios.core.sync``,
and list the sync name in ``__all__``: the MCP server and the HTTP router register
exactly what is named there.

Docstrings are read by agents: one sentence first, then ``Args:`` with examples of
valid values for every parameter. ``/add-endpoint`` walks through the whole recipe.

``meta.published_at`` is filled by the data tasks, the first in the family to fill it:
from ``PSDData_GetDataReleaseInfo`` for the commodity, the release month of the
requested market year (for one country, that country's; for every country or the world,
the latest), reported as the first day of that month at 00:00 UTC because PSD gives the
month only. ``None`` when the release list has no matching record or the answer is
empty. See ``models.DataReleaseInfo``.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

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


def _published_at(
    releases: Sequence[DataReleaseInfo], market_year: int, country_code: str | None
) -> datetime | None:
    """The release month of ``market_year`` as a UTC datetime, or ``None`` when unknown.

    ``country_code`` ``None`` takes the latest release across countries, which is what
    the ``country/all`` and world records carry (``models.CommodityData``).
    """
    months = [
        (release.release_year, release.release_month)
        for release in releases
        if release.market_year == market_year
        and (country_code is None or release.country_code == country_code)
    ]
    if not months:
        return None
    year, month = max(months)
    try:
        return datetime(year, month, 1, tzinfo=UTC)
    except ValueError:
        return None


async def _data_result(
    records: list[CommodityData],
    *,
    endpoint: str,
    commodity_code: str,
    market_year: int,
    country_code: str | None,
    request: dict[str, str | int | None],
) -> Result[list[CommodityData]]:
    published_at = None
    if records:
        releases = await api.PSDData_GetDataReleaseInfo(commodity_code)
        published_at = _published_at(releases, market_year, country_code)
    meta = ResultMeta(source=SOURCE, endpoint=endpoint, published_at=published_at, request=request)
    return Result(data=records, meta=meta)


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
    consumption, stocks, ...): ``attribute_id`` and ``unit_id`` are PSD ids, named by
    ``enums.AttributeId`` and ``enums.UnitId``; ``value`` is in that unit. Codes and the
    year are checked against the packaged lists before any call; an unknown code raises
    ``InvalidRequestError`` naming the closest ones. ``meta.published_at`` is the first
    day of the PSD release month that last revised these figures (from
    ``PSDData_GetDataReleaseInfo``); ``calendar_year`` and ``month`` on each record are
    the same release. An empty list means PSD has no records for that combination; a
    market year without data raises ``NotFoundError``.

    Args:
        commodity_code: PSD commodity code, seven digits, e.g. ``"0410000"`` (Wheat),
            ``"0440000"`` (Corn), ``"2222000"`` (Oilseed, Soybean).
        market_year: PSD market year, e.g. ``2023``; data goes back to 1960 for most
            commodities.
        country_code: PSD country code (not ISO), e.g. ``"US"`` (United States), ``"BR"``
            (Brazil), ``"E4"`` (European Union). Omit it (``None``) for every country:
            one record per country and attribute, up to about 1,900 records. For the
            world total use ``get_world_data``.
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
    return await _data_result(
        records,
        endpoint=endpoint,
        commodity_code=commodity_code,
        market_year=market_year,
        country_code=country_code,
        request=request,
    )


async def get_world_data_async(
    commodity_code: str, market_year: int
) -> Result[list[CommodityData]]:
    """PSD supply and distribution forecasts for one commodity and market year, world total.

    One record per attribute, aggregated by PSD over every applicable country
    (``country_code`` ``"00"``). ``attribute_id`` and ``unit_id`` are PSD ids, named by
    ``enums.AttributeId`` and ``enums.UnitId``; ``value`` is in that unit.
    ``meta.published_at`` is the first day of the latest PSD release month for this
    commodity and market year (from ``PSDData_GetDataReleaseInfo``). The code and the
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
    return await _data_result(
        records,
        endpoint="PSDData_GetWorldCommodityDataByYear",
        commodity_code=commodity_code,
        market_year=market_year,
        country_code=None,
        request=request,
    )


async def get_release_dates_async(commodity_code: str) -> Result[list[DataReleaseInfo]]:
    """When PSD last revised each country and market year of a commodity, by release month.

    One record per country and market year (all years since 1960, several thousand
    records): ``release_year`` and ``release_month`` name the PSD release, a month
    without a day. Use it to fetch only what changed since a previous call. The answer
    is kept for one hour, since it changes at most once a month.

    Args:
        commodity_code: PSD commodity code, seven digits, e.g. ``"0410000"`` (Wheat),
            ``"0440000"`` (Corn), ``"2222000"`` (Oilseed, Soybean).
    """
    validate_commodity_code(commodity_code)
    releases = await api.PSDData_GetDataReleaseInfo(commodity_code)
    meta = ResultMeta(
        source=SOURCE,
        endpoint="PSDData_GetDataReleaseInfo",
        request={"commodity_code": commodity_code},
    )
    return Result(data=releases, meta=meta)


get_data = sync(get_data_async)
get_world_data = sync(get_world_data_async)
get_release_dates = sync(get_release_dates_async)
