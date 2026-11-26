"""Live smoke tests, one per task, skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

``/add-endpoint`` adds them. Sixteen in all, eighteen keyed calls: one each, except the
time series, which spends one per market year (corn, United States, 2021 to 2023,
three); a second time series asks for two attributes of one market year, a second
ranking for one region without PSD's groupings, and the release list and the latest
release are asked once more each with ``since``. The data tasks ask for wheat, United
States, market year 2023, all checked against the packaged lists; the slices for wheat
(balance sheet, latest release), corn (time series) and soybeans (top producers,
2023). The slices record what they answered as test properties (``--junitxml`` shows
them), never a key. The list tasks answer from the package without a call, so their
test fetches the list through its endpoint wrapper and checks that the packaged records
equal it: the freshness check ``reference/README.md`` promises. A difference fails the
test naming what is gone and what is new; ``/refresh-reference-data`` then refreshes the
package.
"""

import re
from collections.abc import Callable
from typing import Any

import pytest
from xippios.usda.fas import Gateway

from xippios.usda.psd import api, tasks
from xippios.usda.psd.enums import AttributeId

pytestmark = [pytest.mark.live, pytest.mark.anyio]

WHEAT, CORN, SOYBEANS = "0410000", "0440000", "2222000"
VINTAGE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


async def test_get_data_live() -> None:
    result = await tasks.get_data_async(WHEAT, 2023, "US")
    assert result.data
    assert {r.country_code for r in result.data} == {"US"}
    assert any(r.attribute_id == AttributeId.PRODUCTION for r in result.data)
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)
    assert result.meta.published_at is None
    snapshot = Gateway.policy.snapshot()
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


async def test_get_time_series_live(record_property: Callable[[str, object], None]) -> None:
    result = await tasks.get_time_series_async(
        CORN, "US", 2021, 2023, attribute_id=AttributeId.PRODUCTION
    )
    assert [r.market_year for r in result.data] == [2021, 2022, 2023]
    assert {(r.country_code, r.attribute_id) for r in result.data} == {("US", 28)}
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)
    record_property("series", [(r.market_year, str(r.value), r.unit_id) for r in result.data])
    record_property("vintage", result.meta.vintage)


async def test_get_time_series_of_several_attributes_live() -> None:
    """``attribute_id`` as a list, one market year: one keyed call."""
    ids = [AttributeId.PRODUCTION, AttributeId.EXPORTS]
    result = await tasks.get_time_series_async(CORN, "US", 2023, 2023, attribute_id=ids)
    assert {(r.country_code, r.market_year) for r in result.data} == {("US", 2023)}
    assert {r.attribute_id for r in result.data} == {28, 88}
    assert result.meta.request["attribute_id"] == [28, 88]
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)


async def test_get_release_dates_since_live() -> None:
    """``since``: one keyed call, the whole wheat list filtered after it."""
    result = await tasks.get_release_dates_async(WHEAT, since="2020-01")
    assert result.data
    assert all((r.release_year, r.release_month) > (2020, 1) for r in result.data)
    assert result.meta.request == {"commodity_code": WHEAT, "since": "2020-01"}


LISTS = [
    # task, operation it came from (meta.endpoint, verbatim), its wrapper in api/
    ("list_commodities", "PSDData_GetCommodities", "get_commodities"),
    ("list_countries", "PSDData_GetCountries", "get_countries"),
    ("list_regions", "PSDData_GetRegions", "get_regions"),
    ("list_units_of_measure", "PSDData_GetUnitsOfMeasure", "get_units_of_measure"),
    ("list_commodity_attributes", "PSDData_GetCommodityAttributes", "get_commodity_attributes"),
]


@pytest.mark.parametrize(("task", "endpoint", "wrapper"), LISTS, ids=[task for task, *_ in LISTS])
async def test_packaged_list_equals_the_live_list(task: str, endpoint: str, wrapper: str) -> None:
    packaged = await getattr(tasks, f"{task}_async")()
    live: list[Any] = await getattr(api, wrapper)()
    stale = [record for record in packaged.data if record not in live]
    new = [record for record in live if record not in packaged.data]
    behind = bool(stale or new)
    assert not behind, (
        f"{task} is behind upstream (fetched {packaged.meta.retrieved_at:%Y-%m-%d}): "
        f"{len(stale)} packaged records upstream no longer sends, {len(new)} upstream "
        "records the package lacks; "
        f"first of each: {stale[:5]}, {new[:5]}. Refresh with /refresh-reference-data."
    )
    assert packaged.data == live, f"{task}: the same records in another order"
    assert packaged.meta.endpoint == endpoint
