"""Live smoke tests: skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

One live smoke test per task function, one keyed call each, three in all. Wheat, United
States, market year 2023, all checked against the packaged lists. The template's
reachability check is gone: it sent the key to ``/``, which the gateway answers 404,
spending a quota call for nothing.
"""

import re

import pytest

from xippios.usda.psd import tasks
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
