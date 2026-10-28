"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.
"""

from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
import respx
from xippios.core import InvalidRequestError, NotFoundError, UnknownCode
from xippios.core.testing import mcp_call

from xippios.usda.psd import tasks
from xippios.usda.psd._client import BASE_URL
from xippios.usda.psd.enums import AttributeId, UnitId
from xippios.usda.psd.errors import NoDataForYear
from xippios.usda.psd.mcp import server

WHEAT, CORN, SOYBEANS = "0410000", "0440000", "2222000"
DATA = "get_country_commodity_data_by_year"
ALL = "get_commodity_data_by_year"
WORLD = "get_world_commodity_data_by_year"
RELEASES = "get_data_release_info"


def test_get_data_for_one_country(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    data = replay_fixture(DATA, "wheat_us_2023")
    result = tasks.get_data(WHEAT, 2023, "US")
    assert data.call_count == 1, "one call: vintage comes from the records"
    assert len(result.data) == 15
    production = next(r for r in result.data if r.attribute_id == AttributeId.PRODUCTION)
    assert production.value == Decimal("49095.0")
    assert production.unit_id == UnitId._1000_MT
    assert result.meta.source == "usda-psd"
    assert result.meta.endpoint == "PSDData_GetCountryCommodityDataByYear"
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 2023,
        "country_code": "US",
    }
    assert result.meta.vintage == "2026-07"
    assert result.meta.published_at is None
    assert data.calls.last.request.headers["Accept"] == "application/json"


def test_get_data_for_every_country(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    """``country/all``: records carry different releases; ``vintage`` is the latest. The
    fixture is cut (ADR-0019), so the shape is checked, not the count."""
    route = replay_fixture(ALL, "wheat_all_2023")
    result = tasks.get_data(WHEAT, 2023)
    assert route.call_count == 1
    assert result.meta.endpoint == "PSDData_GetCommodityDataByYear"
    assert result.meta.request == {"commodity_code": WHEAT, "market_year": 2023}
    assert {r.market_year for r in result.data} == {2023}
    assert len({r.country_code for r in result.data}) > 1
    assert len({(r.calendar_year, r.month) for r in result.data}) > 1
    assert result.meta.vintage == "2026-10"
    assert result.meta.published_at is None


def test_vintage_is_none_for_an_empty_answer() -> None:
    assert tasks._vintage([]) is None


def test_get_release_dates(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    route = replay_fixture(RELEASES, "wheat")
    result = tasks.get_release_dates(WHEAT)
    assert result.data
    assert {r.commodity_code for r in result.data} == {WHEAT}
    assert result.meta.endpoint == "PSDData_GetDataReleaseInfo"
    assert result.meta.request == {"commodity_code": WHEAT}, "filters left None are left out"
    assert result.meta.published_at is None
    assert result.meta.vintage is None
    assert route.call_count == 1


def test_get_release_dates_filters_after_the_one_call(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The cut list holds market years 1960 to 1978 (upstream orders it by market year), so
    the filters are checked on 1975 and against the unfiltered answer."""
    route = replay_fixture(RELEASES, "wheat")
    every = tasks.get_release_dates(WHEAT).data
    one = tasks.get_release_dates(WHEAT, market_year=1975, country_code="US")
    assert [(r.country_code, r.market_year, r.release_year, r.release_month) for r in one.data] == [
        ("US", 1975, 2006, 7)
    ]
    assert one.meta.request == {"commodity_code": WHEAT, "market_year": 1975, "country_code": "US"}
    year = tasks.get_release_dates(WHEAT, market_year=1975)
    assert year.data == [r for r in every if r.market_year == 1975]
    assert len({r.country_code for r in year.data}) == len(year.data), "one per country"
    country = tasks.get_release_dates(WHEAT, country_code="US")
    assert country.data == [r for r in every if r.country_code == "US"]
    assert len({r.market_year for r in country.data}) == len(country.data), "one per market year"
    assert route.call_count == 4


@pytest.mark.anyio
async def test_a_tool_without_a_cap_of_its_own_keeps_cores_default_and_note(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Wheat's release list over MCP, every country and market year: cut at the family's
    default cap with core's note, which promises no filter the tool lacks (ADR-0016)."""
    replay_fixture(RELEASES, "wheat")
    every = tasks.get_release_dates(WHEAT).data
    payload = await mcp_call(server, "usda_psd_get_release_dates", {"commodity_code": WHEAT})
    assert len(payload["data"]) == 200
    assert payload["note"] == (
        f"showing 200 of {len(every)} rows (cap: 200 rows or 65536 bytes); narrow the query to "
        "see the rest"
    )


def test_get_release_dates_validates_its_filters(respx_mock: respx.MockRouter) -> None:
    with pytest.raises(UnknownCode, match="Omit country_code"):
        tasks.get_release_dates(WHEAT, country_code="all")
    with pytest.raises(UnknownCode, match="the release list has no world record"):
        tasks.get_release_dates(WHEAT, country_code="00")
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_release_dates(WHEAT, market_year=23)
    assert not respx_mock.calls


def test_a_market_year_without_data_is_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture(DATA, "unknown_year")
    with pytest.raises(NoDataForYear) as info:
        tasks.get_data(WHEAT, 1900, "US")
    assert info.value.path == "/api/psd/commodity/0410000/country/US/year/1900"
    message = str(info.value)
    assert "commodity 0410000, country US, market year 1900" in message
    assert "upstream answered HTTP 404" in message
    assert route.call_count == 1


def test_unknown_codes_are_refused_before_any_request(respx_mock: respx.MockRouter) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    with pytest.raises(UnknownCode, match="0410000 \\(Wheat\\)"):
        tasks.get_data("0410001", 2023, "US")
    with pytest.raises(UnknownCode, match="'XX' is not a country_code"):
        tasks.get_data(WHEAT, 2023, "XX")
    with pytest.raises(UnknownCode, match="use get_world_data for world data") as world:
        tasks.get_data(WHEAT, 2023, "00")
    assert world.value.closest == ()
    with pytest.raises(UnknownCode, match="Omit country_code for every country"):
        tasks.get_data(WHEAT, 2023, "all")
    with pytest.raises(UnknownCode):
        tasks.get_world_data("9999999", 2023)
    with pytest.raises(UnknownCode):
        tasks.get_release_dates("wheat")
    with pytest.raises(InvalidRequestError, match="four-digit year"):
        tasks.get_data(WHEAT, 23, "US")
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_mcp_tool_call_end_to_end(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture(DATA, "wheat_us_2023")
    payload = await mcp_call(
        server,
        "usda_psd_get_data",
        {"commodity_code": WHEAT, "market_year": 2023, "country_code": "US"},
    )
    assert len(payload["data"]) == 15
    production = next(row for row in payload["data"] if row["attribute_id"] == 28)
    assert production == {
        "commodity_code": "0410000",
        "country_code": "US",
        "market_year": 2023,
        "calendar_year": 2026,
        "month": 7,
        "attribute_id": 28,
        "unit_id": 8,
        "value": 49095.0,
    }
    assert payload["meta"]["endpoint"] == "PSDData_GetCountryCommodityDataByYear"
    assert payload["meta"]["published_at"] is None
    assert payload["meta"]["vintage"] == "2026-07"
    with pytest.raises(AssertionError, match=r"UnknownCode.*0410000 \(Wheat\)"):
        await mcp_call(
            server, "usda_psd_get_data", {"commodity_code": "0410001", "market_year": 2023}
        )


@pytest.mark.anyio
async def test_value_is_a_json_number_through_both_adapters(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """ADR-0008: ``Decimal`` in Python, a JSON number on the wire, never a string."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.psd.http import router

    replay_fixture(WORLD, "wheat_world_2023")
    payload = await mcp_call(
        server, "usda_psd_get_world_data", {"commodity_code": WHEAT, "market_year": 2023}
    )
    values = [row["value"] for row in payload["data"]]
    assert values
    assert all(isinstance(value, float) for value in values)
    app = FastAPI()
    app.include_router(router)
    http = TestClient(app)
    response = http.get(
        "/usda-psd/get_world_data", params={"commodity_code": WHEAT, "market_year": 2023}
    )
    assert response.status_code == 200, response.text
    assert [row["value"] for row in response.json()["data"]] == values
    yields = [row["value"] for row in response.json()["data"] if row["attribute_id"] == 184]
    assert yields == [3.5622]
    rejected = http.get(
        "/usda-psd/get_world_data", params={"commodity_code": "0410001", "market_year": 2023}
    )
    assert rejected.status_code == 422
    assert rejected.json()["title"] == "UnknownCode"


def test_valid_codes_without_data_are_an_empty_result(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Recorded: wheat for Bermuda (BD; PSD's BM is Burma) in 2023 answers 200 with ``[]``.
    Empty means empty, not an error: no vintage, nothing else fetched."""
    route = replay_fixture(DATA, "no_data_valid_codes")
    result = tasks.get_data(WHEAT, 2023, "BD")
    assert result.data == []
    assert (result.meta.vintage, result.meta.published_at) == (None, None)
    assert result.meta.request == {
        "commodity_code": WHEAT,
        "market_year": 2023,
        "country_code": "BD",
    }
    assert route.call_count == 1


def test_a_market_year_without_data_is_not_found_for_every_country(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Recorded: ``country/all`` for 1900 answers 404 with an empty body, like one country."""
    route = replay_fixture(ALL, "year_1900")
    with pytest.raises(NoDataForYear) as info:
        tasks.get_data(WHEAT, 1900)
    assert "commodity 0410000, every country, market year 1900" in str(info.value)
    assert "upstream answered HTTP 404" in str(info.value)
    assert route.call_count == 1


def test_a_market_year_without_data_is_not_found_for_the_world(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Recorded: the world form for 1900 answers 404 with an empty body as well."""
    route = replay_fixture(WORLD, "year_1900")
    with pytest.raises(NoDataForYear) as info:
        tasks.get_world_data(WHEAT, 1900)
    assert "commodity 0410000, the world, market year 1900" in str(info.value)
    assert "upstream answered HTTP 404" in str(info.value)
    assert route.call_count == 1


GATEWAY_NOT_FOUND = {
    "error": {
        "code": "NOT_FOUND",
        "message": "The requested URL was not found on this server.",
    }
}
"""NOT A RECORDING: api.data.gov's documented ``NOT_FOUND`` body, as ``test_client.py``
builds it."""


@pytest.mark.parametrize(
    ("path", "call"),
    [
        ("country/US/year/2023", lambda: tasks.get_data(WHEAT, 2023, "US")),
        ("country/all/year/2023", lambda: tasks.get_data(WHEAT, 2023)),
        ("world/year/2023", lambda: tasks.get_world_data(WHEAT, 2023)),
    ],
    ids=["one_country", "every_country", "world"],
)
def test_the_gateways_not_found_propagates_unchanged(
    respx_mock: respx.MockRouter, path: str, call: Callable[[], object]
) -> None:
    """Only PSD's empty 404 means "no data for this market year"; the gateway's 404 says
    the route is wrong and reaches the caller as classify raised it."""
    path = f"/api/psd/commodity/{WHEAT}/{path}"
    respx_mock.get(f"{BASE_URL}{path}").mock(
        return_value=httpx.Response(404, json=GATEWAY_NOT_FOUND)
    )
    with pytest.raises(NotFoundError) as info:
        call()
    assert not isinstance(info.value, NoDataForYear)
    assert str(info.value).startswith(f"api.data.gov has no route for {path}")
    assert "PSD has no data for commodity" not in str(info.value)
