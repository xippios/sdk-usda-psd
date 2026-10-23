# Reference data for USDA FAS PSD Online

The five code lists PSD publishes ship here as JSON, versioned with the package, and
load through `xippios.usda.psd.params` (built on `xippios.core.reference`):

```python
from xippios.usda.psd.params import packaged_values

packaged_values("commodities").records  # [{"commodityCode": "0577400", ...}, ...], no network call
```

Each file holds upstream's records verbatim, under upstream's field names and in
upstream order, plus the list name (`param`, as the upstream path names it), the
operation it came from (`endpoint`) and the UTC fetch date (`fetched`).

Rules:

- Files come from the upstream through `scripts/refresh_reference.py`
  (`/refresh-reference-data`), never typed in by hand; the script also regenerates
  `enums.py`: `AttributeId` from `commodityAttributes` and `UnitId` from
  `unitsOfMeasure`, as `IntEnum`s. Commodity and country codes stay tables, not enums.
- Every file has a row below naming the endpoint it came from, the date and the count.
- Each packaged list has a lookup task, `list_<thing>`, served as the MCP tool
  `usda_psd_list_<thing>` so agents can form valid calls: `list_commodities`,
  `list_countries`, `list_regions`, `list_units_of_measure`, `list_commodity_attributes`.
  They answer from these files without an upstream call, with the file's `endpoint` as
  `meta.endpoint` and its `fetched` date as `meta.vintage`. A list packaged later gets
  its task through `/refresh-reference-data`.
- Freshness: the live tests (`tests/test_live.py`, `XIPPIOS_LIVE_TESTS=1`) fetch each
  list through its endpoint wrapper and fail when the packaged records differ, naming
  what is gone and what is new.
- Refresh policy: `/refresh-reference-data` inside `/release-prep`, and whenever a
  validation failure names a code the package lacks.
- Public keys: `get_balance_sheet` keys its entries by the names in
  `commodityAttributes.json`, with the id where the list gives one name to several ids.
  A refresh that renames an attribute, or adds an id under an existing name, changes
  those keys: a breaking change under conventions §12, recorded in the CHANGELOG by
  `/refresh-reference-data`.

| File | Origin | Fetched (UTC) | Records |
| --- | --- | --- | --- |
| `commodities.json` | `GET https://api.fas.usda.gov/api/psd/commodities` (`PSDData_GetCommodities`) | 2026-10-23 | 63 |
| `countries.json` | `GET https://api.fas.usda.gov/api/psd/countries` (`PSDData_GetCountries`) | 2026-10-23 | 251 |
| `regions.json` | `GET https://api.fas.usda.gov/api/psd/regions` (`PSDData_GetRegions`) | 2026-10-23 | 15 |
| `unitsOfMeasure.json` | `GET https://api.fas.usda.gov/api/psd/unitsOfMeasure` (`PSDData_GetUnitsOfMeasure`) | 2026-10-23 | 42 |
| `commodityAttributes.json` | `GET https://api.fas.usda.gov/api/psd/commodityAttributes` (`PSDData_GetCommodityAttributes`) | 2026-10-23 | 85 |

The 2026-10-23 files were written by `scripts/refresh_reference.py` from the answers
recorded the same morning in `tests/fixtures/<operation>/all.json` (07:56 UTC), served to
the script's wrappers through `respx` so that the refresh spent no second round of keyed
calls; the records are byte-for-byte the recorded ones.
