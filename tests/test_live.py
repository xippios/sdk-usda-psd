"""Live smoke tests: skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

One live smoke test per task function. The run costs three keyed calls: ``get_data``
(data and release dates) and ``get_world_data`` (data; the release dates come from
``RELEASE_DATES_CACHE``, which live tests share), while ``get_release_dates`` is answered
from the cache. Wheat, United States, market year 2023, all checked against the packaged
lists. The template's reachability check is gone: it sent the key to ``/``, which the
gateway answers 404, spending a quota call for nothing.
"""

from datetime import UTC, datetime

import pytest

from xippios.usda.psd import tasks
from xippios.usda.psd._client import quota
from xippios.usda.psd.enums import AttributeId

pytestmark = [pytest.mark.live, pytest.mark.anyio]

WHEAT = "0410000"


async def test_get_data_live() -> None:
    result = await tasks.get_data_async(WHEAT, 2023, "US")
    assert result.data
    assert {r.country_code for r in result.data} == {"US"}
    assert any(r.attribute_id == AttributeId.PRODUCTION for r in result.data)
    assert result.meta.published_at is not None
    assert result.meta.published_at <= datetime.now(UTC)
    snapshot = quota()
    assert snapshot is not None
    assert snapshot.limit == 1000


async def test_get_world_data_live() -> None:
    result = await tasks.get_world_data_async(WHEAT, 2023)
    assert {r.country_code for r in result.data} == {"00"}
    assert result.meta.published_at is not None


async def test_get_release_dates_live() -> None:
    result = await tasks.get_release_dates_async(WHEAT)
    assert any(r.country_code == "US" and r.market_year == 2023 for r in result.data)
    assert result.meta.published_at is None
