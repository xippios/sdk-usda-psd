"""``GET /api/psd/commodity/{commodityCode}/dataReleaseDates``: release month per record set.

Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetDataReleaseInfo``: path parameter ``commodityCode`` (string); the response
typed only as ``object``. Upstream: "there could be revision on the forecast numbers for
multiple years on a given commodity, and so this API endpoint returns set of records
containing data release dates at a commodity level". The record shape is the recorded
one (``models.DataReleaseInfo``): one per country and market year.

Goes through ``_client.release_client``, which keeps the answer one hour
(``RELEASE_DATES_CACHE``): the data tasks look it up on every call for ``published_at``
and it is large (7,754 records, about 840 KB of JSON for wheat).
"""

from urllib.parse import quote

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, release_client
from xippios.usda.psd.models import DataReleaseInfo

__all__ = ["PSDData_GetDataReleaseInfo"]


async def PSDData_GetDataReleaseInfo(commodity_code: str) -> list[DataReleaseInfo]:
    """Call ``PSDData_GetDataReleaseInfo``, answered from the one-hour cache when fresh.

    Args:
        commodity_code: ``commodityCode``, e.g. ``"0410000"`` (Wheat).

    Returns:
        One ``DataReleaseInfo`` per country and market year, in upstream order.
    """
    path = f"/api/psd/commodity/{quote(commodity_code, safe='')}/dataReleaseDates"
    raw = await release_client.get_json(path)
    return parse(list[DataReleaseInfo], raw, source=SOURCE, endpoint="PSDData_GetDataReleaseInfo")
