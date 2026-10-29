"""``GET /api/psd/commodity/{commodityCode}/world/year/{marketYear}``.

Forecast records of one commodity and market year aggregated to the world, which
upstream describes as "Data from all applicable countries are aggregated together for
reporting it at the World Level". Reference:
``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetWorldCommodityDataByYear``: path parameters ``commodityCode`` (string) and
``marketYear`` (``int32``); the response typed only as ``object``. The record shape is
the recorded one (``models.CommodityData``), with ``countryCode`` ``"00"``.
"""

from urllib.parse import quote

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, client
from xippios.usda.psd.models import CommodityData

__all__ = ["get_world_commodity_data_by_year"]


async def get_world_commodity_data_by_year(
    commodity_code: str, market_year: int
) -> list[CommodityData]:
    """Call ``PSDData_GetWorldCommodityDataByYear``.

    Args:
        commodity_code: ``commodityCode``, e.g. ``"2222000"`` (Oilseed, Soybean).
        market_year: ``marketYear``, e.g. ``2023``.

    Returns:
        One ``CommodityData`` per attribute, in upstream order.

    Raises:
        NotFoundError: Upstream answered HTTP 404.
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    path = f"/api/psd/commodity/{quote(commodity_code, safe='')}/world/year/{market_year}"
    raw = await client.get_json(path)
    return parse(
        list[CommodityData], raw, source=SOURCE, endpoint="PSDData_GetWorldCommodityDataByYear"
    )
