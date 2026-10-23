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
- Each packaged list gets a lookup task, `list_<thing>`, served as the MCP tool
  `usda_psd_list_<thing>` so agents can form valid calls; `/refresh-reference-data`
  adds the task where it is missing.
- Refresh policy: `/refresh-reference-data` inside `/release-prep`, and whenever a
  validation failure names a code the package lacks.

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
