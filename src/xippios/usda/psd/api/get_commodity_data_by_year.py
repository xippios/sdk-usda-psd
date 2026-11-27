"""``GET /api/psd/commodity/{commodityCode}/country/all/year/{marketYear}``.

Forecast records of one commodity and market year for every applicable country.
Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetCommodityDataByYear``: path parameters ``commodityCode`` (string) and
``marketYear`` (``int32``), ``all`` a literal path element; the response typed only as
``object``. The record shape is the recorded one (``models.CommodityData``).

The largest PSD answer: one record per country and attribute, no paging. Recorded
2026-10-28: corn, market year 2023, 1,875 records, 275,759 bytes of JSON, cut to the 91
countries from AF to RH (``corn_all_2023``). A whole answer held 125 countries (its probe
is noted in ``docs/upstream/OBSERVED.md``).
"""

from urllib.parse import quote

from xippios.core import Answer

from xippios.usda.psd._client import client
from xippios.usda.psd.models import CommodityData

__all__ = ["get_commodity_data_by_year"]


async def get_commodity_data_by_year(
    commodity_code: str, market_year: int
) -> Answer[list[CommodityData]]:
    """Call ``PSDData_GetCommodityDataByYear``.

    Args:
        commodity_code: ``commodityCode``, e.g. ``"0440000"`` (Corn).
        market_year: ``marketYear``, e.g. ``2023``.

    Returns:
        The ``Answer``, when it was retrieved and, as its payload, one ``CommodityData`` per
            country and attribute, in upstream order.

    Raises:
        NoDataForYear: Upstream answered HTTP 404 with an empty body (no data for the
            market year), the shared package's ``NotFoundError``.
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    path = f"/api/psd/commodity/{quote(commodity_code, safe='')}/country/all/year/{market_year}"
    return await client.get_answer(
        path, parse=list[CommodityData], endpoint="PSDData_GetCommodityDataByYear"
    )
