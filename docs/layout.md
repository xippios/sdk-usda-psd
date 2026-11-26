# Layout

The files that every source of the family holds are laid out once, in the tree of
sdk-template's README,
[What gets generated](https://github.com/xippios/sdk-template/blob/main/README.md#what-gets-generated).
This file holds what `xippios-usda-psd` adds to that tree, a module, a task file, a
script or a test of its own, each with what it holds, and the change that adds one updates it.

The import path is `xippios.usda.psd` (sdk-core ADR-0006); `src/xippios/` is a
namespace package, and so is `src/xippios/usda/`, the provider level.
Where the API's operation ids repeat across its services, `api/` keeps one module per service
instead, named after the service, and this file says so (conventions §2).

```
src/xippios/usda/psd/
  _client.py       also DATA_PATH, the three data paths, and the gateway of
                   xippios.usda.fas, whose policy keeps the key's quota
  api/             one module per upstream operation, named after it in snake case without
                   the PSDData_ prefix: get_commodities, get_countries, get_regions,
                   get_units_of_measure, get_commodity_attributes,
                   get_country_commodity_data_by_year, get_commodity_data_by_year,
                   get_world_commodity_data_by_year and get_data_release_info; each returns
                   core's Answer
  params.py        also COMMODITIES, COUNTRIES, REGIONS, UNITS and ATTRIBUTES, the packaged
                   lists that a check or a name reads, and the code, year, attribute, region
                   and release month checks
  enums.py         IntEnums AttributeId and UnitId from the packaged id lists; never edited by
                   hand
  reference/       commodities, countries, regions, unitsOfMeasure and commodityAttributes as
                   packaged, and README.md with their provenance
tests/
  test_lists.py    the list tasks answer the recorded lists from the package, without a call
  test_series.py   the time series replays the recorded answers: order, note and ceiling
  test_api.py      replay tests for the endpoint wrappers
  test_client.py   wiring, classify on recorded error bodies, the gateway's quota policy on
                   the recorded 429, core's response cache
  test_params.py   packaged lists, the enums, the code and year checks, the reference script
  test_refresh_upstream.py  the snapshot script's own pages, note and paragraph on the kit
                   of the FAS portal, offline
docs/
  upstream/        also openapi/, the PSD parts of the portal's and the backend's documents,
                   and OBSERVED.md, the notes by hand on what PSD does but never documents
```
