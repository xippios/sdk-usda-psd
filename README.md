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
year; compare it with a stored `meta.vintage`, or pass that vintage as `since`, to fetch
only what changed.

The `list_*` tasks look codes up in the packaged lists, without a call:

```python
from xippios.usda.psd import list_commodities, list_countries

result = list_countries(region_code="R01")  # PSD's region North America (list_regions)
[c.country_code for c in result.data]  # ["CA", "GL", "MX", "SB", "US"], upstream order
result.meta.endpoint, result.meta.retrieved_at  # "PSDData_GetCountries", 2026-10-28T21:42:03Z
list_countries(search="united").data  # TC, UK, US: code, name or GENC code, ignoring case
list_countries(search="usa").data  # US United States, by its GENC code "USA"
list_commodities(search="soybean").data  # meal, oil and oilseed, each also "(Local)"
```

`meta.retrieved_at` of a list is when the package fetched it, and its `meta.vintage` is
`None`, since upstream gives these lists no version. Over MCP `usda_psd_list_countries`
returns all 251 countries through a cap of its own.

`get_time_series` puts together one country's records of a commodity over a range of
market years, one request per market year, and changes none: no derived totals, no unit
conversion, no gap filling.

```python
from xippios.usda.psd import get_time_series
from xippios.usda.psd.enums import AttributeId

series = get_time_series("0440000", "US", 2021, 2023, attribute_id=AttributeId.PRODUCTION)
[(r.market_year, r.value) for r in series.data]  # 3 requests; one record per year with data
get_time_series("0440000", "US", 2023, 2023, attribute_id=[28, 88])  # production and exports
get_time_series("0440000", "US", 2023, 2023)  # every attribute of 2023
```

`get_time_series` starts at 1960 at the earliest, spends one request per market year,
leaves a year without data out, and counts against the hourly quota like every other
request; without `attribute_id` it keeps every attribute.

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
| `PSDData_GetCountryCommodityDataByYear`, one request per market year | `get_time_series(commodity_code, country_code, start_year, end_year, attribute_id=None)` | `usda_psd_get_time_series` | alpha |
| `PSDData_GetDataReleaseInfo` (`commodity/{commodityCode}/dataReleaseDates`) | `get_release_dates(commodity_code, market_year, country_code, since)` | `usda_psd_get_release_dates` | alpha |
| `PSDData_GetCommodities` (`commodities`) | `list_commodities(search)` | `usda_psd_list_commodities` | packaged; `list_*` task |
| `PSDData_GetCountries` (`countries`) | `list_countries(region_code, search)` | `usda_psd_list_countries` | packaged; `list_*` task |
| `PSDData_GetRegions` (`regions`) | `list_regions()` | `usda_psd_list_regions` | packaged; `list_*` task |
| `PSDData_GetUnitsOfMeasure` (`unitsOfMeasure`) | `list_units_of_measure()` | `usda_psd_list_units_of_measure` | packaged; `list_*` task |
| `PSDData_GetCommodityAttributes` (`commodityAttributes`) | `list_commodity_attributes(search)` | `usda_psd_list_commodity_attributes` | packaged; `list_*` task |

0.5.0 covers nine tasks and requires xippios-core 0.5.x (`~=0.5.0`) and xippios-usda-fas
0.1.x (`~=0.1.0`); the ranking `get_top_countries`, the pivot `get_balance_sheet` and the
pick of the newest release `get_latest_release` of 0.4.0 left it, since a source package
answers upstream's records and none of them, and 0.4.0 does not work with core 0.5.0.
Alpha until 1.0: the public surface may change in a minor version (conventions §12);
`CHANGELOG.md` lists every change.

Every request counts against api.data.gov's quota of 1,000 requests per hour per key,
shared by every package using the same `DATA_GOV_API_KEY`; the `list_*` tasks spend none.
The client keeps its own pace of one request per second; once the quota is spent it waits
for the quota to come back when that takes at most 30 s, and otherwise raises
`RateLimitError` with `retry_after` instead of sending.

## Upstream terms and attribution

Data comes from USDA FAS PSD Online (https://apps.fas.usda.gov/psdonline/) under its own terms of use;
this package adds no rights to it. Documentation snapshot: `docs/upstream/`.

## Documents

- sdk-core: [docs/conventions.md](https://github.com/xippios/sdk-core/blob/main/docs/conventions.md) — the conventions every xippios source package follows: its layout, names, results, tests and releases.
- sdk-core: [docs/adr.md](https://github.com/xippios/sdk-core/blob/main/docs/adr.md) — the index of the family's architecture decisions, which the conventions cite.
- sdk-core: [docs/definition-of-done.md](https://github.com/xippios/sdk-core/blob/main/docs/definition-of-done.md) — what a change satisfies before its pull request is opened.
- sdk-core: [docs/review-checklist.md](https://github.com/xippios/sdk-core/blob/main/docs/review-checklist.md) — what the review of a pull request checks, in order.
- sdk-usda-psd: [docs/adr.md](https://github.com/xippios/sdk-usda-psd/blob/main/docs/adr.md) — the index of this package's own decisions, generated from the records in `docs/adr/`.
- sdk-usda-psd: [docs/upstream/FETCHED.md](https://github.com/xippios/sdk-usda-psd/blob/main/docs/upstream/FETCHED.md) — the snapshot of the upstream documentation, the reference for names, parameters and semantics.

## Licence

Apache-2.0. See [LICENSE](https://github.com/xippios/sdk-usda-psd/blob/main/LICENSE).
