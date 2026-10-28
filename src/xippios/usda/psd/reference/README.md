# Reference data for USDA FAS PSD Online

Lists and tables the upstream publishes for every caller alike, shipped with the package
(conventions §3): each `reference/<name>.json` holds `{"param", "endpoint", "fetched",
"records"}` and an optional `"note"`, upstream's records under upstream's field names,
written by `/refresh-reference-data`'s script with `PackagedList.write`, never by hand,
and read with `PackagedList.load`. One row per file: Origin is the endpoint or URL it was
fetched from, or the `docs/upstream/` file it was rebuilt from; Fetched is the UTC time
of that fetch, or the snapshot's `Fetched` time for a rebuilt file.

PSD's five code lists are records, kept in upstream order with upstream's values (unit
descriptions padded with spaces to 20 characters). `commodityAttributes` and
`unitsOfMeasure`, lists of integer ids, make `enums.AttributeId` and `enums.UnitId`; the
commodity, country and region codes stay tables. The `list_*` tasks answer from these
files without an upstream call, and `params` checks codes and attribute ids against them.
`get_balance_sheet` keys its entries by the names in `commodityAttributes.json`, with the
id where the list gives one name to several ids, so a refresh that renames an attribute,
or adds an id under an existing name, changes those keys: a breaking change, recorded in
`CHANGELOG.md` when the lists are refreshed (conventions §12). The nightly live tests
compare each packaged list with the live one (`test_packaged_list_equals_the_live_list`
in `tests/test_live.py`, one keyed call per list) and name the records that are gone and
those that are new: the signal to run `/refresh-reference-data`.

| File | Origin | Fetched (UTC) | Records |
| --- | --- | --- | --- |
| `commodities.json` | `GET https://api.fas.usda.gov/api/psd/commodities` (`PSDData_GetCommodities`) | 2026-10-23 | 63 |
| `countries.json` | `GET https://api.fas.usda.gov/api/psd/countries` (`PSDData_GetCountries`) | 2026-10-23 | 251 |
| `regions.json` | `GET https://api.fas.usda.gov/api/psd/regions` (`PSDData_GetRegions`) | 2026-10-23 | 15 |
| `unitsOfMeasure.json` | `GET https://api.fas.usda.gov/api/psd/unitsOfMeasure` (`PSDData_GetUnitsOfMeasure`) | 2026-10-23 | 42 |
| `commodityAttributes.json` | `GET https://api.fas.usda.gov/api/psd/commodityAttributes` (`PSDData_GetCommodityAttributes`) | 2026-10-23 | 85 |

The 2026-10-23 files were written by `scripts/refresh_reference.py` from the answers
recorded the same morning, now in `tests/fixtures/<wrapper>/all.json` (07:56 UTC), served to
the script's wrappers through `respx` so that the refresh spent no second round of keyed
calls; the records are byte-for-byte the recorded ones.
Their `fetched` is the bare date the script then wrote, which `PackagedList.load` reads
as 00:00 UTC of that day (so the list tasks' `meta.retrieved_at`) until the next refresh
writes the full time.
