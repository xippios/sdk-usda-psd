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

from xippios.core import Answer

from xippios.usda.psd._client import client
from xippios.usda.psd.models import DataReleaseInfo

__all__ = ["get_data_release_info"]


async def get_data_release_info(commodity_code: str) -> Answer[list[DataReleaseInfo]]:
    """Call ``PSDData_GetDataReleaseInfo``.

    Args:
        commodity_code: ``commodityCode``, e.g. ``"0410000"`` (Wheat).

    Returns:
        The ``Answer``, when it was retrieved and, as its payload, one ``DataReleaseInfo`` per
            country and market year, in upstream order.

    Raises:
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    path = f"/api/psd/commodity/{quote(commodity_code, safe='')}/dataReleaseDates"
    return await client.get_answer(
        path, parse=list[DataReleaseInfo], endpoint="PSDData_GetDataReleaseInfo"
    )
