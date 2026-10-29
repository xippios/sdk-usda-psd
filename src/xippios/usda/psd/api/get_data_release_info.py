"""``GET /api/psd/commodity/{commodityCode}/dataReleaseDates``: release month per record set.

Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetDataReleaseInfo``: path parameter ``commodityCode`` (string); the response
typed only as ``object``. Upstream: "there could be revision on the forecast numbers for
multiple years on a given commodity, and so this API endpoint returns set of records
containing data release dates at a commodity level". The record shape is the recorded
one (``models.DataReleaseInfo``): one per country and market year, every market year
since 1960 (7,754 records, about 840 KB of JSON for wheat). Error shapes are mapped once
in ``xippios.usda.psd._client.classify``.
"""

from urllib.parse import quote

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, client
from xippios.usda.psd.models import DataReleaseInfo

__all__ = ["get_data_release_info"]


async def get_data_release_info(commodity_code: str) -> list[DataReleaseInfo]:
    """Call ``PSDData_GetDataReleaseInfo``.

    Args:
        commodity_code: ``commodityCode``, e.g. ``"0410000"`` (Wheat).

    Returns:
        One ``DataReleaseInfo`` per country and market year, in upstream order.

    Raises:
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    path = f"/api/psd/commodity/{quote(commodity_code, safe='')}/dataReleaseDates"
    raw = await client.get_json(path)
    return parse(list[DataReleaseInfo], raw, source=SOURCE, endpoint="PSDData_GetDataReleaseInfo")
