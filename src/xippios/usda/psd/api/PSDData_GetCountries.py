"""``GET /api/psd/countries``: every PSD country with its region.

Reference: ``docs/upstream/openapi/portal-document.json``, operation
``PSDData_GetCountries``: no parameters, the response typed only as ``object``.
The record shape is the recorded one, ``tests/fixtures/PSDData_GetCountries/all.json``,
parsed into ``models.Country``. Error shapes are mapped once in
``xippios.usda.psd._client.classify``.
"""

from xippios.core import parse

from xippios.usda.psd._client import SOURCE, client
from xippios.usda.psd.models import Country

__all__ = ["PSDData_GetCountries"]


async def PSDData_GetCountries() -> list[Country]:
    """Call ``PSDData_GetCountries``.

    Returns:
        Every PSD country with its region, in upstream order, one ``Country`` per
        record, e.g.
            ``Country(country_code="US", country_name="United States",
            region_code="R01", genc_code="USA")``

    Raises:
        AuthError: api.data.gov refused the key in ``DATA_GOV_API_KEY``.
        RateLimitError: api.data.gov's hourly quota for the key is spent.
    """
    raw = await client.get_json("/api/psd/countries")
    return parse(list[Country], raw, source=SOURCE, endpoint="PSDData_GetCountries")
