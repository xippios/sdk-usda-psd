"""Live smoke tests: skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

One live smoke test per task function, twelve in all, fourteen keyed calls: one each,
except the time series, which spends one per market year (corn, United States, 2021 to
2023, three). The data tasks ask for wheat, United States, market year 2023, all
checked against the packaged lists; the slices for wheat (balance sheet, latest
release), corn (time series) and soybeans (top producers, 2023). The slices record what
they answered as test properties (``--junitxml`` shows them), never a key. The list
tasks answer from the package without a call, so their test fetches the list through
its endpoint wrapper and checks that the packaged records equal it: the
freshness check ``reference/README.md`` promises. A difference fails the test naming
what is gone and what is new; ``/refresh-reference-data`` then refreshes the package.
Next to them, the template's reachability check, ``test_upstream_answers``, sends no
key: a plain request to ``BASE_URL`` that spends no quota call.
"""

import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from xippios.usda.psd import api, tasks
from xippios.usda.psd._client import BASE_URL, config, policy
from xippios.usda.psd.enums import AttributeId

pytestmark = [pytest.mark.live, pytest.mark.anyio]

WHEAT, CORN, SOYBEANS = "0410000", "0440000", "2222000"
VINTAGE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


async def test_upstream_answers() -> None:
    """The base URL answers without a server error (sdk-template's reachability check).

    A plain request, not the package's client, so no key goes out and no call counts
    against the key's quota; a keyed gateway's answer to it (a 403 or a 404, say) still
    shows the host is up.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": config.user_agent},
        timeout=config.timeouts.to_httpx(),
        follow_redirects=True,
    ) as http:
        response = await http.get(BASE_URL)
    assert response.status_code < 500


async def test_get_data_live() -> None:
    result = await tasks.get_data_async(WHEAT, 2023, "US")
    assert result.data
    assert {r.country_code for r in result.data} == {"US"}
    assert any(r.attribute_id == AttributeId.PRODUCTION for r in result.data)
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)
    assert result.meta.published_at is None
    snapshot = policy.snapshot()
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


async def test_get_balance_sheet_live(record_property: Callable[[str, object], None]) -> None:
    result = await tasks.get_balance_sheet_async(WHEAT, "US", 2023)
    sheet = result.data
    assert (sheet.commodity_code, sheet.country_code, sheet.market_year) == (WHEAT, "US", 2023)
    assert sheet.attributes["Production"].attribute_id == AttributeId.PRODUCTION
    ids = [entry.attribute_id for entry in sheet.attributes.values()]
    assert len(ids) == len(set(ids)), "one entry per record"
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)
    assert result.meta.published_at is None
    record_property("attributes", list(sheet.attributes))
    record_property("vintage", result.meta.vintage)


async def test_get_time_series_live(record_property: Callable[[str, object], None]) -> None:
    result = await tasks.get_time_series_async(CORN, "US", AttributeId.PRODUCTION, 2021, 2023)
    assert [r.market_year for r in result.data] == [2021, 2022, 2023]
    assert {(r.country_code, r.attribute_id) for r in result.data} == {("US", 28)}
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)
    record_property("series", [(r.market_year, str(r.value), r.unit_id) for r in result.data])
    record_property("vintage", result.meta.vintage)


async def test_get_top_countries_live(record_property: Callable[[str, object], None]) -> None:
    result = await tasks.get_top_countries_async(SOYBEANS, 2023, AttributeId.PRODUCTION, n=5)
    assert len(result.data) == 5
    values = [r.value for r in result.data]
    assert values == sorted(values, reverse=True)
    assert {r.attribute_id for r in result.data} == {28}
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)
    record_property("top", [(r.country_code, str(r.value), r.unit_id) for r in result.data])
    record_property("vintage", result.meta.vintage)


async def test_get_latest_release_live(record_property: Callable[[str, object], None]) -> None:
    result = await tasks.get_latest_release_async(WHEAT)
    releases = {(r.release_year, r.release_month) for r in result.data}
    assert len(releases) == 1
    ((year, month),) = releases
    assert result.meta.vintage == f"{year:04d}-{month:02d}"
    assert result.meta.published_at is None
    record_property("vintage", result.meta.vintage)
    record_property("records", len(result.data))


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
