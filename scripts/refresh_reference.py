"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

The script declares the packaged lists in one ``Lists`` of ``xippios.core.refresh``, one
``Listed`` each, and runs them on core's frame (conventions §3), which does the rest as in
every source: it fetches every list through its layer-1 wrapper in ``api/``, never through a
task that might answer from the package, before it writes one, through the package's client
with one attempt per request, so a 5xx or a 429 spends no second call of the key's quota,
and prints the requests it sent and the quota left that the gateway reported in its
``REMAINING_HEADER``, a failed run's too, each wrapper's ``Answer`` read by its payload.
Then it writes each list to ``reference/<name>.json`` by ``PackagedList.write``, the list's
name, the upstream operation it came from (the ``operationId`` its ``Listed`` names, never
the wrapper's name: conventions §2), the UTC time of the fetch to the second and upstream's
records under upstream's field names, rewrites the rows of the provenance table of
``reference/README.md`` and renders ``enums.py``, formatted by ruff as it is committed, all
as one.

PSD publishes five lists, all of them records: ``unitsOfMeasure`` and
``commodityAttributes`` are lists of integer ids, which make ``UnitId`` and ``AttributeId``,
an ``IntEnum`` each, so that a member compares equal to the id in upstream's data (sdk-core
ADR-0031, decision 6); a name that several ids share takes ``_<id>``, ``TOTAL_DISAPPEARANCE_126``
and ``TOTAL_DISAPPEARANCE_173``. ``commodities``, ``countries`` and ``regions`` stay tables,
not enums. The list endpoints take the api.data.gov key, so ``DATA_GOV_API_KEY`` must be in
the environment; run from the repository root::

    uv run python scripts/refresh_reference.py

Five requests against api.data.gov's hourly quota, shared with every package using the key,
each sent once. ``--only <list> [<list> ...]`` fetches the named lists alone and keeps every
other list's file; ``--render-only`` writes the provenance rows and ``enums.py`` from the
packaged files alone, without a request and without a key, as after a core release that
changes the renderer (conventions §15).
"""

from xippios.core import PackagedList
from xippios.core.refresh import Enumeration, Listed, Lists, run
from xippios.usda.fas import REMAINING_HEADER

from xippios.usda.psd import api
from xippios.usda.psd._client import BASE_URL, client
from xippios.usda.psd.params import PACKAGE, PACKAGED_LISTS


def origin(packaged: PackagedList) -> str:
    """The provenance row's Origin: the request the list was fetched by and its operation."""
    return f"`GET {BASE_URL}/api/psd/{packaged.param}` (`{packaged.endpoint}`)"


LISTS = Lists(
    package=PACKAGE,
    lists=(
        Listed(
            "commodities",
            api.get_commodities,
            endpoint="PSDData_GetCommodities",
            origin=origin,
        ),
        Listed("countries", api.get_countries, endpoint="PSDData_GetCountries", origin=origin),
        Listed("regions", api.get_regions, endpoint="PSDData_GetRegions", origin=origin),
        Listed(
            "unitsOfMeasure",
            api.get_units_of_measure,
            endpoint="PSDData_GetUnitsOfMeasure",
            enum=Enumeration(ids="unitId", names="unitDescription"),
            origin=origin,
        ),
        Listed(
            "commodityAttributes",
            api.get_commodity_attributes,
            endpoint="PSDData_GetCommodityAttributes",
            enum=Enumeration(ids="attributeId", names="attributeName"),
            origin=origin,
        ),
    ),
    packaged=PACKAGED_LISTS,
    client=client,
    quota_header=REMAINING_HEADER,
)
"""Each packaged list, named as the upstream path names it, in the order of the provenance
table. Its operation verbatim, as the snapshot's ``operationId`` and the wrapper's
``endpoint=`` give it, which the file keeps as its ``endpoint`` and the list task as its
``meta.endpoint``; the fields of each enum as upstream names them. Together they are
``params.PACKAGED_LISTS``, which the frame checks before a request."""


if __name__ == "__main__":
    raise SystemExit(run(LISTS))
