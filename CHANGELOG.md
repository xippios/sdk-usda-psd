# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

Adopted xippios-core 0.3.0, sdk-template v0.3.0 and conventions 1.22 (conventions §15).

### Changed

- BREAKING: requires xippios-core 0.3.x (`xippios-core~=0.3.0`), and the `mcp`, `http`
  and `testing` extras name `xippios-core[...]~=0.3.0` likewise, in place of `~=0.2.0`.
- BREAKING: the `list_*` tasks' `meta` is built by core's `PackagedList` (ADR-0022, rule
  1): `meta.retrieved_at` is when the packaged list was fetched (the file's `fetched`, a
  UTC time to the second since the refresh of 2026-10-28), no longer when the task
  answered, and `meta.vintage` is `None`, no longer the fetch date.
- `meta.request` leaves out a parameter left `None`: `get_data` without `country_code`,
  `get_release_dates` without its filters, and the `list_*` tasks without theirs.
- BREAKING: `_client.policy` gives way to `_client.gateway`, core's
  `xippios.core.data_gov.Gateway`, whose `Gateway.policy` is the one quota policy per
  process for `DATA_GOV_API_KEY`. The gateway's `API_KEY_*` refusals, its 429 and its
  `NOT_FOUND` keep their error classes; a 429's message no longer says "Nothing was
  retried"; a request into a spent quota waits within the policy's `pause_cap` (30 s by
  default) or is refused with `source` `"api.data.gov"`, not `"usda-psd"`, and a message
  that starts "api.data.gov quota of the key in DATA_GOV_API_KEY spent".
- An unknown code or attribute id is refused with core's `UnknownCode`, an
  `InvalidRequestError` as before: its message reads "'0410001' is not a commodity_code
  in the packaged commodities list (fetched 2026-10-28). Did you mean ...", ends "If
  upstream added it since, the packaged list needs a refresh (/refresh-reference-data).",
  its `fetched` is a datetime and its `closest` a tuple.
- An MCP tool argument the schema refuses is answered
  `error: InvalidRequestError: <argument>: <message>` (core 0.3.0).
- `enums.py` is rendered by core's `render_enums` and formatted by ruff;
  `AttributeId`, `UnitId`, their members and values are unchanged.
  `scripts/refresh_reference.py` writes the packaged lists with core's
  `PackagedList.write` and `dump_upstream`, `fetched` as a UTC time to the second.
- `scripts/check-siblings.sh` is replaced by the template's
  `.github/scripts/check-siblings.sh`, which `siblings.yml` runs and which finds the
  siblings under `xippios.usda` itself.
- From sdk-template v0.2.1 to v0.3.0: `tests/test_family.py`, core's family check,
  replaces `tests/test_layout.py`, `tests/test_adapters.py` and two structural tests of
  `tests/test_tasks.py`; `publish.yml` tags a release from its merge; `ci.yml` checks the
  CHANGELOG entry and the fixture cap; `gates.yml` arrives switched off; `CLAUDE.md`
  imports the family rules from `.claude/family.md`.
- BREAKING: the nine endpoint wrappers take conventions 1.22 §2's names, module and
  function alike: the upstream operation in snake case without the `PSDData_` prefix
  every operation shares, so `PSDData_GetCommodityDataByYear` is
  `get_commodity_data_by_year` in `api/get_commodity_data_by_year.py`, and likewise
  `get_commodities`, `get_commodity_attributes`, `get_countries`,
  `get_country_commodity_data_by_year`, `get_data_release_info`, `get_regions`,
  `get_units_of_measure` and `get_world_commodity_data_by_year`. The old names are no
  longer importable from `xippios.usda.psd.api`. The fixture directories follow
  (`tests/fixtures/get_commodities/`, conventions §10); the three fixtures over the
  256 KiB cap are re-recorded, cut, under the new names (below). `meta.endpoint` and the
  packaged lists' `endpoint` keep the verbatim operation id
  (`"PSDData_GetCommodityDataByYear"`), and the tasks, MCP tools and HTTP routes are
  unchanged.
- BREAKING: `get_time_series` takes `(commodity_code, country_code, start_year,
  end_year, attribute_id=None)`: `attribute_id` moves after `end_year`, so a positional
  call of 0.2.0 (`get_time_series("0440000", "US", 28, 2021, 2023)`) no longer works;
  name it, `attribute_id=28`. It takes an id, a list of ids (`[28, 88]`) or, omitted,
  every attribute; each year's records come in upstream's order, every id is checked
  before the first request, an empty list is refused, and `meta.request` carries
  `attribute_id` as given or leaves it out. Since the parameter takes a list, the HTTP
  route is `POST /usda-psd/get_time_series` with a JSON body, no longer `GET` with query
  parameters (conventions §9). MCP calls name their arguments and are unaffected.
- `get_top_countries` gains `region_code` (rank one PSD region's countries, mapped
  through the packaged countries list, checked before the call against the regions
  the packaged countries carry, `R15` included; an unknown one is `UnknownCode` naming
  the closest, and `R00`, World, a hint that the world total is `get_world_data`'s) and
  `exclude_groupings` (`True` leaves out `tasks.GROUPINGS`, PSD's eight
  aggregates: `E4`, `E2`, `E3`, `C1`, `T3`, `X8`, `Z7`, `ZZ`); by default nothing is
  excluded, as before. `meta.vintage` is the latest release among the records ranked
  after both apply, and `meta.request` now carries `exclude_groupings`.
- `get_release_dates` and `get_latest_release` gain `since`, a release month
  `"YYYY-MM"` as `meta.vintage` writes it, checked before the call: `get_release_dates`
  keeps the records of releases strictly after it, `get_latest_release` answers an empty
  list when the newest release is not later, `meta.vintage` still naming that release.
- Over MCP, `get_data`, `get_release_dates` and `get_time_series` keep the 200 rows or
  64 KB, and a cut answer's note names their filters: "filter by country_code to see the
  rest", "filter by market_year, country_code or since to see the rest", "filter by
  attribute_id or narrow start_year and end_year to see the rest" (conventions §8,
  ADR-0016).
- `tests/test_slices.py` pins the key `get_balance_sheet` gives each of the 85 packaged
  attribute ids, so a reference refresh that renames an attribute or adds an id under an
  existing name fails a test and is recorded here as a breaking change (conventions §12).
- The three fixtures over the 256 KiB cap are re-recorded on 2026-10-28, cut at 200,000
  bytes and marked `truncated` (ADR-0019): `get_commodity_data_by_year/corn_all_2023.json`
  (1,360 of 1,875 records), `get_commodity_data_by_year/wheat_all_2023.json` (1,359 of
  1,845) and `get_data_release_info/wheat.json` (1,851 of 7,754, market years 1960 to
  1978, the list being ordered by market year); the tests assert what the cut answers
  hold.
- The five packaged lists are refreshed from upstream on 2026-10-28
  (`/refresh-reference-data`, five keyed calls), each file's `fetched` now the UTC time
  of its fetch to the second (`countries.json`: `2026-10-28T21:42:03Z`), which the
  `list_*` tasks give as `meta.retrieved_at` and `UnknownCode` names as "fetched
  2026-10-28", as do `enums.py`'s class docstrings. Records unchanged, none changed,
  added or gone: commodities 63, countries 251, regions 15, units of measure 42,
  commodity attributes 85; `get_balance_sheet`'s keys and the `AttributeId` and `UnitId`
  members stay as they were.

### Removed

- `xippios.usda.psd.errors.UnknownCode`, replaced by `xippios.core.UnknownCode`.
- `params.PackagedList` and `params.packaged_values`: core's
  `PackagedList.load(params.PACKAGE, name)` reads a packaged list.

## [0.2.0] - 2026-10-26

### Changed

- BREAKING: requires xippios-core 0.2.x (~=0.2.0); 0.1.0 does not work on core 0.2.0
  (`AsyncClient.get` passes `auth=` to a `request` override that did not take it, so the
  first request raised `TypeError`). The `mcp`, `http` and `testing` extras name
  `xippios-core[...]~=0.2.0` likewise (conventions §12, ADR-0018).
- Adopts xippios-core 0.2.0, sdk-template v0.2.0 and conventions 1.13 (conventions §15).
- The client's quota handling is core's `QuotaPolicy` (ADR-0015), installed on the
  gateway's `x-ratelimit-limit` and `x-ratelimit-remaining` with a one-hour `window`:
  `QuotaAwareClient` and its cache probe, `Quota`, `quota()`, `observe_quota`,
  `quota_pause` and `QUOTA_WINDOW` are removed from `_client`, and `_client.policy`
  with `policy.snapshot()` replaces `quota()`. A spent quota still waits within
  `RetryPolicy.backoff_max` or raises `RateLimitError` without sending.
- A 429 is retried only when its wait is within `RetryPolicy.backoff_max`: core asks
  `classify` before it retries (ADR-0015), so a 429 without `Retry-After` is raised after
  one request with the one-hour `retry_after`, not after four. Its message describes the
  policy's snapshot and says that nothing was retried.
- Error messages quote the gateway's text with its URL written `<host>` (conventions §5,
  ADR-0005 amendment).
- `usda_psd_list_countries` returns all 251 countries over MCP through a cap of its own,
  `tasks.MCP_CAPS` (ADR-0016), passed by `mcp.py`; every other tool keeps 200 rows or
  64 KB, with core's note "narrow the query to see the rest". The docstring of
  `list_countries` no longer tells agents to filter past the cap.
- `enums.py` re-rendered by core's `render_int_enums` (ADR-0008 amendment): members and
  values unchanged; the docstrings are ASCII-only and `__all__` lists one name per line.
  `scripts/refresh_reference.py` drops `render_id_enums` and `member_names` for
  `render_int_enums` with `id_name_pairs`, needs no formatting step after a refresh, and
  takes `--render-only` to regenerate `enums.py` from the packaged files without a request.
  It has the template's shape: `ID_LISTS` for `unitsOfMeasure` and `commodityAttributes`,
  the two id lists, and `TABLES` of its own for commodities, countries and regions; the
  packaged files are unchanged.
- Tests: `tests/conftest.py` drops `placeholder_api_key`, `PLACEHOLDER_KEY` and
  `fresh_quota`, and `test_tasks.py` drops `test_replay_tests_send_the_placeholder_key`:
  core's pytest plugin pins the key named in `xippios_placeholder_key_envs` and forgets
  every quota snapshot around each offline test (ADR-0013). The tests of the quota
  machinery core now owns go from `test_client.py`; one test, marked `rate_limited`,
  replays the recorded 429 through the policy.
- mypy checks `scripts/` too; `tests/test_layout.py` walks the namespace levels up to
  `xippios` and stops there (sdk-template v0.2.0).
- The sdist ships no tests: `tests` leaves its include list, whose patterns are anchored
  (sdk-template v0.2.0).
- `tests/test_live.py` has the template's reachability check `test_upstream_answers` again:
  a plain request to the base URL without the key, so it spends no quota call. The twelve
  keyed tests are unchanged.
- CI: `ci.yml` is the template's, core's file byte for byte, and runs pre-commit too; the
  ADR-0006 sibling proof moves to `.github/workflows/siblings.yml`.
  `.github/workflows/live.yml` runs the live tests nightly at 01:25 UTC and on demand
  (conventions §10).
- From sdk-template v0.2.0 too: `publish.yml` refuses a `pyproject.toml` with
  `[tool.uv.sources]`; `.secrets.baseline` drops the `is_swagger_file` filter, so the
  Swagger snapshots in `docs/upstream/` are scanned now; the new `/adopt-release` command
  and the re-rendered `.claude/commands`.

## [0.1.0] - 2026-10-24

### Added

- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for USDA FAS PSD Online, MCP server and FastAPI router wired to the task
  layer, test harness, CI and publishing.
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
  empty: PSD gives a month, no day. A market year without data is `NoDataForYear`,
  a `NotFoundError`, naming commodity, country and year. `get_release_dates` filters
  upstream's full list by market year and country, for polling over MCP.
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
- Slices, as MCP tools `usda_psd_get_*` and HTTP routes, composing the existing
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
  the closest ids and takes an integer value and its own reason.
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
  which the gateway answers 404, spending a quota call. Each task has its own live smoke
  test instead, twelve in all.
