# xippios-usda-psd

Typed Python client, MCP server and FastAPI routes for
[USDA FAS PSD Online](https://apps.fas.usda.gov/psdonline/), part of the
[xippios SDK family](https://github.com/xippios). Names and semantics follow the
upstream documentation; every response carries release metadata (source, endpoint,
retrieved_at, published_at, vintage).

## Install

```bash
uv add xippios-usda-psd            # client only
uv add "xippios-usda-psd[mcp]"     # + MCP server
uv add "xippios-usda-psd[http]"    # + FastAPI router
```

Set `DATA_GOV_API_KEY` in the environment. Nothing is read from files.

## 30-second example

```python
from xippios.usda.psd import get_data
from xippios.usda.psd.enums import AttributeId

result = get_data("0410000", 2023, "US")  # wheat, market year 2023, United States
production = next(r for r in result.data if r.attribute_id == AttributeId.PRODUCTION)
production.value, production.unit_id  # Decimal('49095.0'), 8 (UnitId._1000_MT)
result.meta.vintage  # "2026-07": the PSD release that last revised these figures
result.meta.published_at  # None: PSD gives a month, no day
result.meta.retrieved_at, result.meta.request
```

Codes are PSD's own (commodity `0410000` wheat, `0440000` corn, `2222000` soybeans;
country `US`, `BR`, `E4`), checked against the lists packaged in `reference/` before any
call. Leave out the country for every country at once, or use `get_world_data` for the
world total. `attribute_id` and `unit_id` are PSD's integer ids; `enums.AttributeId` and
`enums.UnitId` name the packaged ones and compare equal to them. The MCP server returns
at most 200 rows per call, and every country at once is up to about 1,900 rows, so pass a
country there. `get_release_dates` tells when PSD last revised each country and market
year; compare it with a stored `meta.vintage` to fetch only what changed.

The `list_*` tasks look codes up in the packaged lists, without a call:

```python
from xippios.usda.psd import list_commodities, list_countries

result = list_countries(region_code="R01")  # PSD's region North America (list_regions)
[c.country_code for c in result.data]  # ["CA", "GL", "MX", "SB", "US"], upstream order
result.meta.endpoint, result.meta.vintage  # "PSDData_GetCountries", "2026-10-23" (fetched)
list_countries(search="united").data  # TC, UK, US: code, name or GENC code, ignoring case
list_countries(search="usa").data  # US United States, by its GENC code "USA"
list_commodities(search="soybean").data  # meal, oil and oilseed, each also "(Local)"
```

`meta.vintage` of a list is the day the package fetched it (upstream gives these lists no
version), `meta.retrieved_at` when the task answered. Over MCP `usda_psd_list_countries`
returns all 251 countries through a cap of its own.

The slices answer the common questions from the same operations. They select, order or
pivot upstream's records and change none: no derived totals, no unit conversion, no gap
filling.

```python
from xippios.usda.psd import (
    get_balance_sheet,
    get_latest_release,
    get_time_series,
    get_top_countries,
)
from xippios.usda.psd.enums import AttributeId

sheet = get_balance_sheet("0410000", "US", 2023).data  # wheat, United States, one request
list(sheet.attributes)  # ["Area Harvested", "Beginning Stocks", "Production", ...], 15
sheet.attributes["Production"]  # attribute_id=28, unit_id=8 (1000 MT), value=Decimal("49095.0")

series = get_time_series("0440000", "US", AttributeId.PRODUCTION, 2021, 2023)  # 3 requests
[(r.market_year, r.value) for r in series.data]  # one record per year with data, oldest first

top = get_top_countries("2222000", 2023, AttributeId.PRODUCTION, n=5)  # soybeans, one request
[r.country_code for r in top.data]  # largest first; "E4" (EU) and aggregates rank too

latest = get_latest_release("0410000")  # the countries and market years of the newest release
latest.meta.vintage  # "2026-10", comparable with get_data's meta.vintage
```

`get_balance_sheet` keys each entry by the attribute's upstream name; an id whose name
upstream gives to several ids (`"Total Disappearance"` is 126 and 173) always carries the
id, `"Total Disappearance (126)"`, and each entry keeps its own `unit_id`.
`get_time_series` starts at 1960 at the earliest, spans at most 100 market years per
call, spends one request per market year,
leaves a year without data out, and counts against the hourly quota like every other
request.
`get_top_countries` excludes nothing: PSD's groupings (`E4` European Union, `T3` Africa,
NEC, ...) rank alongside countries; filter with `list_countries` if you must.

## MCP

```json
{
  "mcpServers": {
    "usda-psd": {
      "command": "uvx",
      "args": ["--from", "xippios-usda-psd[mcp]", "xippios-usda-psd-mcp"],
      "env": { "DATA_GOV_API_KEY": "..." }
    }
  }
}
```

Tools are read-only and named `usda_psd_<verb>_<noun>`. Results are capped at
200 rows or 64 KB with a note on how to narrow the query; `usda_psd_list_countries` has a
cap of its own, 300 rows, so all 251 countries arrive. `--http` serves streamable HTTP
instead of stdio.

## Status

| Upstream operation | Task function | MCP tool | Status |
| --- | --- | --- | --- |
| `PSDData_GetCountryCommodityDataByYear` (`commodity/{commodityCode}/country/{countryCode}/year/{marketYear}`) | `get_data(commodity_code, market_year, country_code)` | `usda_psd_get_data` | alpha |
| `PSDData_GetCommodityDataByYear` (`commodity/{commodityCode}/country/all/year/{marketYear}`) | `get_data(commodity_code, market_year)` | `usda_psd_get_data` | alpha |
| `PSDData_GetWorldCommodityDataByYear` (`commodity/{commodityCode}/world/year/{marketYear}`) | `get_world_data(commodity_code, market_year)` | `usda_psd_get_world_data` | alpha |
| `PSDData_GetDataReleaseInfo` (`commodity/{commodityCode}/dataReleaseDates`) | `get_release_dates(commodity_code, market_year, country_code)` | `usda_psd_get_release_dates` | alpha |
| `PSDData_GetCommodities` (`commodities`) | `list_commodities(search)` | `usda_psd_list_commodities` | packaged; `list_*` task |
| `PSDData_GetCountries` (`countries`) | `list_countries(region_code, search)` | `usda_psd_list_countries` | packaged; `list_*` task |
| `PSDData_GetRegions` (`regions`) | `list_regions()` | `usda_psd_list_regions` | packaged; `list_*` task |
| `PSDData_GetUnitsOfMeasure` (`unitsOfMeasure`) | `list_units_of_measure()` | `usda_psd_list_units_of_measure` | packaged; `list_*` task |
| `PSDData_GetCommodityAttributes` (`commodityAttributes`) | `list_commodity_attributes(search)` | `usda_psd_list_commodity_attributes` | packaged; `list_*` task |

The slices: task-shaped functions over the operations above, no new endpoint.

| Upstream operation | Task function | MCP tool | Example | Status |
| --- | --- | --- | --- | --- |
| `PSDData_GetCountryCommodityDataByYear`, one request | `get_balance_sheet(commodity_code, country_code, market_year)` | `usda_psd_get_balance_sheet` | `get_balance_sheet("0410000", "US", 2023)`: wheat US 2023 as one record, 15 attributes | alpha |
| `PSDData_GetCountryCommodityDataByYear`, one request per market year | `get_time_series(commodity_code, country_code, attribute_id, start_year, end_year)` | `usda_psd_get_time_series` | `get_time_series("0440000", "US", 28, 2021, 2023)`: US corn production, three years | alpha |
| `PSDData_GetCommodityDataByYear`, one request | `get_top_countries(commodity_code, market_year, attribute_id, n=10)` | `usda_psd_get_top_countries` | `get_top_countries("2222000", 2023, 28, n=5)`: the five largest soybean producers | alpha |
| `PSDData_GetDataReleaseInfo`, one request | `get_latest_release(commodity_code)` | `usda_psd_get_latest_release` | `get_latest_release("0410000")`: what wheat's newest release revised; MCP returns at most 200 rows, a release adding a market year can exceed that (wheat 2026-10: 146), `get_release_dates(commodity_code, market_year=..., country_code=...)` returns any part in full | alpha |

0.2.0 covers the same twelve tasks as 0.1.0 and requires xippios-core 0.2.x
(`~=0.2.0`); 0.1.0 does not work with core 0.2.0. Alpha until 1.0: the public surface
may change in a minor version (conventions §12); `CHANGELOG.md` lists every change.

Every request counts against api.data.gov's quota of 1,000 requests per hour per key,
shared by every package using the same `DATA_GOV_API_KEY`; the `list_*` tasks spend none.
The client keeps its own pace of one request per second; once the quota is spent it waits
for the quota to come back when that takes at most 30 s, and otherwise raises
`RateLimitError` with `retry_after` instead of sending.

## Upstream terms and attribution

Data comes from USDA FAS PSD Online (https://apps.fas.usda.gov/psdonline/) under its own terms of use;
this package adds no rights to it. Documentation snapshot: `docs/upstream/`.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
