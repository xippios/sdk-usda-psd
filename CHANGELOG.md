# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for USDA FAS PSD Online, empty task layer, MCP server and FastAPI router
  wired to it, test harness, CI and publishing.
- Upstream documentation snapshot in `docs/upstream/` (2026-10-23): the PSD part of
  the FAS Open Data Services Swagger 2.0 document as the portal loads it
  (`openapi/portal-document.json`) and as the API serves it itself
  (`openapi/backend-docs-v1.json`), nine `/api/psd/` operations each, the
  ESR and GATS paths left out. `FETCHED.md` records the full documents' sizes and
  sha256 and the pages that hold no documentation text.
- `scripts/refresh_upstream.py`: regenerates the snapshot reproducibly, stdlib only and
  without a key (`uv run scripts/refresh_upstream.py`).
- Endpoint wrappers for the nine PSD operations, named after the snapshot's
  operationIds: the five reference lists (`PSDData_GetCommodities`, `PSDData_GetCountries`,
  `PSDData_GetRegions`, `PSDData_GetUnitsOfMeasure`, `PSDData_GetCommodityAttributes`),
  the data by country, for every country and for the world
  (`PSDData_GetCountryCommodityDataByYear`, `PSDData_GetCommodityDataByYear`,
  `PSDData_GetWorldCommodityDataByYear`) and the release dates
  (`PSDData_GetDataReleaseInfo`). Models mirror the recorded records: `CommodityData`
  with `value` as `Decimal` and attribute and unit ids as plain `int`, so a new upstream
  id never fails an answer, and `DataReleaseInfo`.
- Tasks `get_data(commodity_code, market_year, country_code=None)` (one country, or every
  country through the `country/all` path), `get_world_data(commodity_code, market_year)`
  and `get_release_dates(commodity_code, market_year=None, country_code=None)`, as MCP
  tools `usda_psd_get_data`, `usda_psd_get_world_data`, `usda_psd_get_release_dates`
  and HTTP routes. Codes and the market year are checked before any call. The data
  tasks set `meta.vintage` to the PSD release that last revised the result, the latest
  `calendarYear`-`month` of its records (`"2026-07"`), and leave `meta.published_at`
  empty: PSD gives a month, no day. A market year without data is `NotFoundError`
  naming commodity, country and year. `get_release_dates` filters upstream's full list
  by market year and country, for polling over MCP.
- Tasks `list_commodities(search=None)`, `list_countries(region_code=None, search=None)`,
  `list_regions()`, `list_units_of_measure()` and `list_commodity_attributes(search=None)`,
  as MCP tools `usda_psd_list_*` and HTTP routes. They answer from the packaged lists
  without an upstream call, records in upstream order and unchanged; `meta.endpoint` is
  the operation the list was fetched from, `meta.vintage` the day it was fetched
  (`"2026-10-23"`), `meta.retrieved_at` when the task answered, `meta.request` the
  filters. `search` keeps records whose code or name (for countries also the GENC code)
  contains the text, ignoring case;
  `region_code` keeps the countries of one region, exactly (`"R15"`, which
  `PSDData_GetRegions` lacks, included; an unknown region is an empty list), so agents
  can see past the MCP cap of 200 rows (251 countries). Live tests check each packaged
  list against the live one.
- Wave 2 slices, as MCP tools `usda_psd_get_*` and HTTP routes, composing the existing
  wrappers and packaged lists, records unchanged (ADR-0003):
  `get_balance_sheet(commodity_code, country_code, market_year)` pivots one country-year
  into one `BalanceSheet` record, lossless, its `attributes` keyed by the packaged
  attribute name (with the id for an id whose name the list gives to several ids, so a key
  is the same in every answer of a package version; `"attribute <id>"` for an id the list
  lacks), each `BalanceSheetEntry` with its own `unit_id`; an empty answer is
  `NotFoundError`. `get_time_series(commodity_code, country_code, attribute_id,
  start_year, end_year)` makes one request per market year from 1960 on, at most 100
  market years per call, oldest first, and leaves a year without data (`NoDataForYear`)
  or without the attribute out, no gap filled; any other error is raised.
  `get_top_countries(commodity_code, market_year, attribute_id, n=10)` ranks the
  `country/all` records of one attribute by value, ties in upstream order, groupings
  such as `E4` included; `meta.vintage` is the latest release among every record ranked.
  `get_latest_release(commodity_code)` keeps the records of the newest release, with
  that release as `meta.vintage`; over MCP at most 200 rows, `get_release_dates` serves
  any part of the list in full.
- `errors.NoDataForYear`, a `NotFoundError`: `classify` raises it for PSD's empty
  `text/plain` 404 on a data path, the answer for a market year without data, and the
  data tasks raise it again naming commodity, country and year; the gateway's
  `NOT_FOUND` stays a plain `NotFoundError` and reaches the caller unchanged.
- `params.validate_attribute_id` and `params.attribute_names`: attribute ids are checked
  against the packaged `commodityAttributes` list before any call; `UnknownCode` names
  the closest ids and now takes an integer value and its own reason.
- Client (ADR-0010): `classify` maps api.data.gov's `API_KEY_*` answers to `AuthError`
  naming the code and `DATA_GOV_API_KEY`, a 429 to `RateLimitError` (`Retry-After`, else
  one hour), the gateway's `NOT_FOUND` to `NotFoundError` and PSD's empty-body 404 to
  `NoDataForYear`, a `NotFoundError`. The
  client keeps 60 requests per minute, one at a time, asks for JSON, and records the
  gateway's `x-ratelimit-*` headers in `quota()`, never from a cache hit. Once the
  hourly quota is spent it waits before the next request when the wait is within
  `RetryPolicy.backoff_max`, and otherwise raises `RateLimitError` with `retry_after`
  without sending; a request the cache can answer is never delayed or refused.
- Packaged reference data: the five lists under `reference/` with provenance, written by
  `scripts/refresh_reference.py` through `api/`; `enums.AttributeId` and `enums.UnitId`
  (`IntEnum`, named after upstream's names); `params.validate_commodity_code`,
  `validate_country_code` (raising `errors.UnknownCode` with the closest packaged codes,
  or a hint for `"all"` and `"00"`) and `validate_market_year`.
- Recorded fixtures: the five lists; wheat US, wheat and corn for every country, wheat
  and soybeans world, all 2023; wheat US 2021 and 2022 for the time series; the wheat
  release dates; an unknown commodity, country and market year; valid codes without
  data (wheat, Bermuda, 2023: 200 `[]`); market year 1900 for every country and the
  world (404, empty body); an invalid key; and the gateway's 429 (`OVER_RATE_LIMIT`,
  `Retry-After: 3151`, `x-ratelimit-remaining: 0`), recorded after spending the hourly
  quota. `CLAUDE.md` records what each answered.
- `scripts/check-siblings.sh` and the CI job `siblings`: this wheel and
  `xippios-usda-nass` install side by side, import, pass `uv pip check`, and add no
  `__init__.py` to `xippios/` or `xippios/usda/` (ADR-0006).

### Removed

- The template's live reachability test `test_upstream_answers`: it sent the key to `/`,
  which the gateway answers 404, spending a quota call. The three per-task live tests
  remain.
