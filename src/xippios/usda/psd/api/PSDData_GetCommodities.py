"""``GET /api/psd/commodities``: every PSD commodity with its code.

Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetCommodities``: no parameters, the response typed only as ``object``.
The record shape is the recorded one, ``tests/fixtures/PSDData_GetCommodities/all.json``,
parsed into ``models.Commodity``. Error shapes are mapped once in
``xippios.usda.psd._client.classify``.
"""

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, client
from xippios.usda.psd.models import Commodity

__all__ = ["PSDData_GetCommodities"]


async def PSDData_GetCommodities() -> list[Commodity]:
    """Call ``PSDData_GetCommodities``.

    Returns:
        Every PSD commodity with its code, in upstream order, one ``Commodity`` per
        record, e.g.
            ``Commodity(commodity_code="0410000", commodity_name="Wheat")``

    Raises:
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    raw = await client.get_json("/api/psd/commodities")
    return parse(list[Commodity], raw, source=SOURCE, endpoint="PSDData_GetCommodities")
