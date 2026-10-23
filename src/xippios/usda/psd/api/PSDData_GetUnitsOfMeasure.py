"""``GET /api/psd/unitsOfMeasure``: every PSD unit of measure with its id.

Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetUnitsOfMeasure``: no parameters, the response typed only as ``object``.
The record shape is the recorded one, ``tests/fixtures/PSDData_GetUnitsOfMeasure/all.json``,
parsed into ``models.UnitOfMeasure``. Error shapes are mapped once in
``xippios.usda.psd._client.classify``.
"""

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, client
from xippios.usda.psd.models import UnitOfMeasure

__all__ = ["PSDData_GetUnitsOfMeasure"]


async def PSDData_GetUnitsOfMeasure() -> list[UnitOfMeasure]:
    """Call ``PSDData_GetUnitsOfMeasure``.

    Returns:
        Every PSD unit of measure with its id, in upstream order, one ``UnitOfMeasure`` per
        record, e.g.
            ``UnitOfMeasure(unit_id=8, unit_description="(1000 MT)           ")``

    Raises:
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    raw = await client.get_json("/api/psd/unitsOfMeasure")
    return parse(list[UnitOfMeasure], raw, source=SOURCE, endpoint="PSDData_GetUnitsOfMeasure")
