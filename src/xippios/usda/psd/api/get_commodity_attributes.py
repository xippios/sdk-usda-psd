"""``GET /api/psd/commodityAttributes``: every PSD commodity attribute with its id.

Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetCommodityAttributes``: no parameters, the response typed only as ``object``.
The record shape is the recorded one, ``tests/fixtures/get_commodity_attributes/all.json``,
parsed into ``models.CommodityAttribute``. Error shapes are mapped once in
``xippios.usda.psd._client.classify``.
"""

from xippios.core import Answer

from xippios.usda.psd._client import client
from xippios.usda.psd.models import CommodityAttribute

__all__ = ["get_commodity_attributes"]


async def get_commodity_attributes() -> Answer[list[CommodityAttribute]]:
    """Call ``PSDData_GetCommodityAttributes``.

    Returns:
        The ``Answer``, when it was retrieved and, as its payload, every PSD commodity attribute
            with its id, in upstream order, one ``CommodityAttribute`` per record, e.g.
            ``CommodityAttribute(attribute_id=28, attribute_name="Production")``

    Raises:
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    return await client.get_answer(
        "/api/psd/commodityAttributes",
        parse=list[CommodityAttribute],
        endpoint="PSDData_GetCommodityAttributes",
    )
