"""Live smoke tests: skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

One live smoke test per task function, one keyed call each, eight in all. The data
tasks ask for wheat, United States, market year 2023, all checked against the packaged
lists. The list tasks answer from the package without a call, so their test fetches the
list through its endpoint wrapper and checks that the packaged records equal it: the
freshness check ``reference/README.md`` promises. A difference fails the test naming
what is gone and what is new; ``/refresh-reference-data`` then refreshes the package.
The template's reachability check is gone: it sent the key to ``/``, which the gateway
answers 404, spending a quota call for nothing.
"""

import re
from typing import Any

import pytest

from xippios.usda.psd import api, tasks
from xippios.usda.psd._client import quota
from xippios.usda.psd.enums import AttributeId

pytestmark = [pytest.mark.live, pytest.mark.anyio]

WHEAT = "0410000"
VINTAGE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


async def test_get_data_live() -> None:
    result = await tasks.get_data_async(WHEAT, 2023, "US")
    assert result.data
    assert {r.country_code for r in result.data} == {"US"}
    assert any(r.attribute_id == AttributeId.PRODUCTION for r in result.data)
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)
    assert result.meta.published_at is None
    snapshot = quota()
    assert snapshot is not None
    assert snapshot.limit == 1000


async def test_get_world_data_live() -> None:
    result = await tasks.get_world_data_async(WHEAT, 2023)
    assert {r.country_code for r in result.data} == {"00"}
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)


async def test_get_release_dates_live() -> None:
    result = await tasks.get_release_dates_async(WHEAT, market_year=2023, country_code="US")
    assert len(result.data) == 1
    assert result.data[0].release_month in range(1, 13)
    assert result.meta.published_at is None


LISTS = [
    ("list_commodities", "PSDData_GetCommodities"),
    ("list_countries", "PSDData_GetCountries"),
    ("list_regions", "PSDData_GetRegions"),
    ("list_units_of_measure", "PSDData_GetUnitsOfMeasure"),
    ("list_commodity_attributes", "PSDData_GetCommodityAttributes"),
]


@pytest.mark.parametrize(("task", "endpoint"), LISTS, ids=[task for task, _ in LISTS])
async def test_packaged_list_equals_the_live_list(task: str, endpoint: str) -> None:
    packaged = await getattr(tasks, f"{task}_async")()
    live: list[Any] = await getattr(api, endpoint)()
    stale = [record for record in packaged.data if record not in live]
    new = [record for record in live if record not in packaged.data]
    behind = bool(stale or new)
    assert not behind, (
        f"{task} is behind upstream (packaged {packaged.meta.vintage}): {len(stale)} packaged "
        f"records upstream no longer sends, {len(new)} upstream records the package lacks; "
        f"first of each: {stale[:5]}, {new[:5]}. Refresh with /refresh-reference-data."
    )
    assert packaged.data == live, f"{task}: the same records in another order"
    assert packaged.meta.endpoint == endpoint
