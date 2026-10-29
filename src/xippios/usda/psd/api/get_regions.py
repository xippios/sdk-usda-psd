"""``GET /api/psd/regions``: every PSD region.

Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetRegions``: no parameters, the response typed only as ``object``.
The record shape is the recorded one, ``tests/fixtures/get_regions/all.json``,
parsed into ``models.Region``. Error shapes are mapped once in
``xippios.usda.psd._client.classify``.
"""

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, client
from xippios.usda.psd.models import Region

__all__ = ["get_regions"]


async def get_regions() -> list[Region]:
    """Call ``PSDData_GetRegions``.

    Returns:
        Every PSD region, in upstream order, one ``Region`` per
        record, e.g.
            ``Region(region_code="R00", region_name="World")``

    Raises:
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    raw = await client.get_json("/api/psd/regions")
    return parse(list[Region], raw, source=SOURCE, endpoint="PSDData_GetRegions")
