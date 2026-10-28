"""``GET /api/psd/commodityAttributes``: every PSD commodity attribute with its id.

Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetCommodityAttributes``: no parameters, the response typed only as ``object``.
The record shape is the recorded one, ``tests/fixtures/PSDData_GetCommodityAttributes/all.json``,
parsed into ``models.CommodityAttribute``. Error shapes are mapped once in
``xippios.usda.psd._client.classify``.
"""

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, client
from xippios.usda.psd.models import CommodityAttribute

__all__ = ["get_commodity_attributes"]


async def get_commodity_attributes() -> list[CommodityAttribute]:
    """Call ``PSDData_GetCommodityAttributes``.

    Returns:
        Every PSD commodity attribute with its id, in upstream order, one ``CommodityAttribute`` per
        record, e.g.
            ``CommodityAttribute(attribute_id=28, attribute_name="Production")``

    Raises:
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    raw = await client.get_json("/api/psd/commodityAttributes")
    return parse(
        list[CommodityAttribute], raw, source=SOURCE, endpoint="PSDData_GetCommodityAttributes"
    )
