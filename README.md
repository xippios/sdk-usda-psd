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
list_countries(search="united").data  # TC, UK, US: code or name, ignoring case
list_commodities(search="soybean").data  # meal, oil and oilseed, each also "(Local)"
```

`meta.vintage` of a list is the day the package fetched it (upstream gives these lists no
version), `meta.retrieved_at` when the task answered. Over MCP `usda_psd_list_countries`
stops at 200 of its 251 countries, before the United States; pass `region_code` or
`search` there.

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
200 rows or 64 KB with a note on how to narrow the query. `--http` serves streamable
HTTP instead of stdio.

## Status

| Upstream operation | Task function | MCP tool | Status |
| --- | --- | --- | --- |
| `PSDData_GetCountryCommodityDataByYear` (`commodity/{commodityCode}/country/{countryCode}/year/{marketYear}`) | `get_data(commodity_code, market_year, country_code)` | `usda_psd_get_data` | done |
| `PSDData_GetCommodityDataByYear` (`commodity/{commodityCode}/country/all/year/{marketYear}`) | `get_data(commodity_code, market_year)` | `usda_psd_get_data` | done |
| `PSDData_GetWorldCommodityDataByYear` (`commodity/{commodityCode}/world/year/{marketYear}`) | `get_world_data(commodity_code, market_year)` | `usda_psd_get_world_data` | done |
| `PSDData_GetDataReleaseInfo` (`commodity/{commodityCode}/dataReleaseDates`) | `get_release_dates(commodity_code, market_year, country_code)` | `usda_psd_get_release_dates` | done |
| `PSDData_GetCommodities` (`commodities`) | `list_commodities(search)` | `usda_psd_list_commodities` | packaged; `list_*` task |
| `PSDData_GetCountries` (`countries`) | `list_countries(region_code, search)` | `usda_psd_list_countries` | packaged; `list_*` task |
| `PSDData_GetRegions` (`regions`) | `list_regions()` | `usda_psd_list_regions` | packaged; `list_*` task |
| `PSDData_GetUnitsOfMeasure` (`unitsOfMeasure`) | `list_units_of_measure()` | `usda_psd_list_units_of_measure` | packaged; `list_*` task |
| `PSDData_GetCommodityAttributes` (`commodityAttributes`) | `list_commodity_attributes(search)` | `usda_psd_list_commodity_attributes` | packaged; `list_*` task |

Every request counts against api.data.gov's quota of 1,000 requests per hour per key,
shared by every package using the same `DATA_GOV_API_KEY`; the `list_*` tasks spend none.
The client keeps its own pace of one request per second; once the quota is spent it waits
out a wait of up to 30 s and otherwise raises `RateLimitError` with `retry_after` instead
of sending.

## Upstream terms and attribution

Data comes from USDA FAS PSD Online (https://apps.fas.usda.gov/psdonline/) under its own terms of use;
this package adds no rights to it. Documentation snapshot: `docs/upstream/`.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
