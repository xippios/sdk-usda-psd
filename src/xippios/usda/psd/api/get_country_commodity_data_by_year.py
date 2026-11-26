"""``GET /api/psd/commodity/{commodityCode}/country/{countryCode}/year/{marketYear}``.

Forecast records of one commodity, country and market year. Reference:
``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetCountryCommodityDataByYear``: three path parameters, ``commodityCode`` and
``countryCode`` strings, ``marketYear`` an ``int32``; the response typed only as
``object``. The record shape is the recorded one (``models.CommodityData``).

Recorded answers: an unknown commodity or country code is HTTP 200 with ``[]``
(``unknown_commodity``, ``unknown_country``); a market year without data is HTTP 404
with an empty body (``unknown_year``), which ``_client.classify`` maps to the shared
package's ``NoDataForYear``.
"""

from urllib.parse import quote

from xippios.core import Answer

from xippios.usda.psd._client import client
from xippios.usda.psd.models import CommodityData

__all__ = ["get_country_commodity_data_by_year"]


async def get_country_commodity_data_by_year(
    commodity_code: str, country_code: str, market_year: int
) -> Answer[list[CommodityData]]:
    """Call ``PSDData_GetCountryCommodityDataByYear``.

    Args:
        commodity_code: ``commodityCode``, e.g. ``"0410000"`` (Wheat).
        country_code: ``countryCode``, PSD's code, e.g. ``"US"``.
        market_year: ``marketYear``, e.g. ``2023``.

    Returns:
        The ``Answer``, when it was retrieved and, as its payload, one ``CommodityData`` per
            attribute, in upstream order; ``[]`` when upstream has none.

    Raises:
        NoDataForYear: Upstream answered HTTP 404 with an empty body (no data for the
            market year), the shared package's ``NotFoundError``.
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    path = (
        f"/api/psd/commodity/{quote(commodity_code, safe='')}"
        f"/country/{quote(country_code, safe='')}/year/{market_year}"
    )
    return await client.get_answer(
        path, parse=list[CommodityData], endpoint="PSDData_GetCountryCommodityDataByYear"
    )
