"""``GET /api/psd/commodity/{commodityCode}/country/all/year/{marketYear}``.

Forecast records of one commodity and market year for every applicable country.
Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetCommodityDataByYear``: path parameters ``commodityCode`` (string) and
``marketYear`` (``int32``), ``all`` a literal path element; the response typed only as
``object``. The record shape is the recorded one (``models.CommodityData``).

The largest PSD answer: one record per country and attribute, no paging. Corn, market
year 2023: 1,875 records from 125 countries, 275,759 bytes of JSON (2026-10-23,
``corn_all_2023``).
"""

from urllib.parse import quote

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, client
from xippios.usda.psd.models import CommodityData

__all__ = ["get_commodity_data_by_year"]


async def get_commodity_data_by_year(commodity_code: str, market_year: int) -> list[CommodityData]:
    """Call ``PSDData_GetCommodityDataByYear``.

    Args:
        commodity_code: ``commodityCode``, e.g. ``"0440000"`` (Corn).
        market_year: ``marketYear``, e.g. ``2023``.

    Returns:
        One ``CommodityData`` per country and attribute, in upstream order.

    Raises:
        NotFoundError: Upstream answered HTTP 404.
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    path = f"/api/psd/commodity/{quote(commodity_code, safe='')}/country/all/year/{market_year}"
    raw = await client.get_json(path)
    return parse(list[CommodityData], raw, source=SOURCE, endpoint="PSDData_GetCommodityDataByYear")
