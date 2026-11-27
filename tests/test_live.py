"""Live smoke tests: skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

Each task that sends a request has a live smoke test: ``get_data`` and ``get_world_data`` for
wheat, market year 2023, the first for the United States; ``get_release_dates`` for wheat's
United States 2023 and once more with ``since``; and ``get_time_series`` for corn in the United
States, 2021 to 2023 for production, one call per market year, and once more for production
and exports of 2023. The five list tasks, ``list_commodities``, ``list_countries``,
``list_regions``, ``list_units_of_measure`` and ``list_commodity_attributes``, answer from the
packaged lists and send no request, so no live test calls them: their data is held against
upstream by core's nightly comparison of the packaged lists, which fetches each list of
``LIVE_LISTS`` through its wrapper, one keyed call each (sdk-core ADR-0055), the signal to run
``/refresh-reference-data``. The tests record what the series answered as test properties
(``--junitxml`` shows them), never a key. Core's testing plugin prints the run's requests as
``requests sent by the live run: <n>``, the count in the log of ``live.yml`` that
``/release-prep`` cites; core's response cache answers a second read of a path within its
lifetime, the release list with ``since`` and the series' 2023 among them, so the run sends
fewer requests than its calls.
"""

import re
from collections.abc import Callable

import pytest
from xippios.core.testing.live import *  # noqa: F403
from xippios.usda.fas import Gateway

from xippios.usda.psd import api, tasks
from xippios.usda.psd.enums import AttributeId
from xippios.usda.psd.params import ATTRIBUTES, COMMODITIES, COUNTRIES, REGIONS, UNITS

pytestmark = [pytest.mark.live, pytest.mark.anyio]

LIVE_LISTS = {  # each packaged list compared, by its file reference/<name>.json
    "commodities": (COMMODITIES, api.get_commodities),
    "countries": (COUNTRIES, api.get_countries),
    "regions": (REGIONS, api.get_regions),
    "unitsOfMeasure": (UNITS, api.get_units_of_measure),
    "commodityAttributes": (ATTRIBUTES, api.get_commodity_attributes),
}
NO_LIVE_LIST: dict[str, str] = {}  # every packaged list is compared

WHEAT, CORN = "0410000", "0440000"
VINTAGE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


async def test_get_data_live() -> None:
    result = await tasks.get_data_async(WHEAT, 2023, country_code="US")
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
        CORN, "US", start_year=2021, end_year=2023, attribute_id=AttributeId.PRODUCTION
    )
    assert [r.market_year for r in result.data] == [2021, 2022, 2023]
    assert {(r.country_code, r.attribute_id) for r in result.data} == {("US", 28)}
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)
    (note,) = result.meta.notes
    assert note.startswith("Market years in the order of the rows: 2021 with 1 row"), note
    record_property("series", [(r.market_year, str(r.value), r.unit_id) for r in result.data])
    record_property("vintage", result.meta.vintage)


async def test_get_time_series_of_several_attributes_live() -> None:
    """``attribute_id`` as a list, one market year, which core's cache answers where the series
    above read it within its lifetime."""
    ids = [AttributeId.PRODUCTION, AttributeId.EXPORTS]
    result = await tasks.get_time_series_async(
        CORN, "US", start_year=2023, end_year=2023, attribute_id=ids
    )
    assert {(r.country_code, r.market_year) for r in result.data} == {("US", 2023)}
    assert {r.attribute_id for r in result.data} == {28, 88}
    assert result.meta.request["attribute_id"] == [28, 88]
    assert result.meta.vintage is not None
    assert VINTAGE.match(result.meta.vintage)


async def test_get_release_dates_since_live() -> None:
    """``since``: the whole wheat list filtered after it, which core's cache answers where the
    test above read it within its lifetime."""
    result = await tasks.get_release_dates_async(WHEAT, since="2020-01")
    assert result.data
    assert all((r.release_year, r.release_month) > (2020, 1) for r in result.data)
    assert result.meta.request == {"commodity_code": WHEAT, "since": "2020-01"}
