# sdk-usda-psd — instructions for Claude Code

`xippios-usda-psd` wraps USDA FAS PSD Online as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file is the contract for every session
that works here; the family rules it points to apply as well.

@.claude/family.md

## What this package wraps

| | |
| --- | --- |
| Upstream | USDA FAS PSD Online, https://apps.fas.usda.gov/psdonline/ |
| API base URL | `https://api.fas.usda.gov` |
| Documentation | https://apps.fas.usda.gov/opendatawebV2/, snapshotted in `docs/upstream/` |
| Credentials | `DATA_GOV_API_KEY` from the environment, sent as the `X-Api-Key` header by `xippios.core.data_gov`'s `Gateway` (`_client.auth` is `gateway.auth`); the key is api.data.gov's, shared by every package that reads it. ADR-0009: one key variable per issuer when one key serves several sources, so every source reached through api.data.gov (`usda-psd`, `usda-esr`, `usda-gats`) reads `DATA_GOV_API_KEY`, and one key is one gateway quota |
| Rate limit | ADR-0010, decisions 1–5. Pace: 60 requests per minute, burst 1 (`RateLimit(per_minute=60, burst=1)` in `_client.py`, enforced client-side): a self-imposed pace, upstream documents none (the snapshot names no limit). Quota: api.data.gov's 1,000 requests per rolling hour per key, reported in `x-ratelimit-limit` / `x-ratelimit-remaining` (the hourly quota, not a pace) and shared by every package and process using the same `DATA_GOV_API_KEY`; it may be spent, it is not pre-rationed. The quota is the gateway's: `Gateway.policy` of `xippios.core.data_gov`, one `QuotaPolicy` per process for the key, which `_client.py` installs with `gateway.install` (ADR-0009, ADR-0015), keeps the snapshot from every answer from the wire, never a cache hit's, and gates: once the quota is spent the next request waits it out inside the call, logged, when that is within the policy's `pause_cap` (30 s by default), and otherwise raises `RateLimitError` with `retry_after` without sending, a refusal that speaks for `api.data.gov` (its `source`). The wait counts from the last answer: a 429's `Retry-After`, else the policy's `window` of one hour (the gateway sends no reset header, and the 200 that leaves `remaining` at 0 no `Retry-After`). `gateway.classify`, which `classify` asks first, maps the 429 to `RateLimitError` with `retry_after` the wait the policy keeps the quota spent for, from `Retry-After` (recorded: 3151 s, `over_rate_limit.json`), else 3600 s, and core shapes its retries from that: a wait beyond `RetryPolicy.backoff_max` is raised after one request. In offline tests core's pytest plugin bypasses the limiter and the quota policy and forgets the snapshot around each test; a test that asserts a wait or a refusal is marked `rate_limited` |
| Write tools | no, this package is read-only |

The snapshot in `docs/upstream/` is the reference for names, parameters and semantics.

## Upstream behaviour established by fixtures

The snapshot types every response as `object`, so these facts come from the answers
recorded on 2026-10-23 under `tests/fixtures/`; `_client.classify` maps them once.

- Record shapes of the five lists are in `models.py`, each naming its fixture. Unit
  descriptions are padded with spaces to 20 characters (kept); attribute names are not
  unique (`Total Disappearance` is 126 and 173); four countries sit in region `R15`,
  which `PSDData_GetRegions` does not list.
- Unknown commodity code (`commodity/9999999/country/US/year/2023`) and unknown country
  code (`commodity/0410000/country/XX/year/2023`): HTTP 200 with `[]`. Empty means
  empty, not an error; `params.validate_commodity_code` / `validate_country_code` refuse
  unknown codes before the call (`UnknownCode`, naming the closest packaged codes).
- Valid codes without data: wheat for Bermuda 2023 (`commodity/0410000/country/BD/year/2023`;
  PSD's `BM` is Burma, which has wheat data) answers HTTP 200 with `[]`
  (`no_data_valid_codes`). Empty means empty: `get_data` returns an empty list.
- Market year without data: HTTP 404 with an empty `text/plain` body on every data form,
  one country (`commodity/0410000/country/US/year/1900`, `unknown_year`), every country
  (`.../country/all/year/1900`) and the world (`.../world/year/1900`, both `year_1900`),
  mapped to `errors.NoDataForYear`, a `NotFoundError` (only that answer on a data path:
  an empty 404 elsewhere or the gateway's `NOT_FOUND` stays a plain `NotFoundError`).
  `get_time_series` skips such a year; the other data tasks re-raise it as
  `NoDataForYear` naming commodity, country and year. Any other `NotFoundError` (the
  gateway's `NOT_FOUND`) propagates unchanged from every task.
- Invalid key: HTTP 403 `{"error": {"code": "API_KEY_INVALID", "message": "An invalid
  api_key was supplied. Get one at https://api.fas.usda.gov:443"}}`, no quota headers;
  mapped to `AuthError` naming the code and `DATA_GOV_API_KEY`. The other documented
  `API_KEY_*` codes map the same way. The gateway's `NOT_FOUND` 404 is a plain
  `NotFoundError` (no such route; not recorded, `test_client` builds the documented shape).
- Quota: every keyed answer carries `x-ratelimit-limit: 1000` and
  `x-ratelimit-remaining`; `via` names api.data.gov's API Umbrella. Spent on purpose on
  2026-10-23 (987 calls at the client's pace; its own gate then refused to send) and
  recorded from a fresh process (`get_commodities/over_rate_limit.json`): HTTP 429,
  `{"error": {"code": "OVER_RATE_LIMIT", "message": "You have exceeded your rate limit.
  Try again later or contact us for assistance: https://api.fas.usda.gov:443"}}`,
  `Retry-After: 3151`, `x-ratelimit-limit: 1000`, `x-ratelimit-remaining: 0`. The client
  uses that `Retry-After`; the one-hour fallback (api.data.gov: "The block will
  automatically be lifted by waiting an hour") applies to the 200 that left `remaining`
  at 0, which carries no `Retry-After`, and to a 429 without one.
- Data records (`PSDData_GetCountryCommodityDataByYear`, `PSDData_GetCommodityDataByYear`,
  `PSDData_GetWorldCommodityDataByYear`; `models.CommodityData`): `commodityCode`,
  `countryCode` (`"00"` in world records), `marketYear`, `calendarYear` and `month` as
  digit strings (`"2023"`, `"2026"`, `"07"`, parsed to `int`), `attributeId` and `unitId`
  as integers (plain `int` in the model, so an id PSD adds before the next reference
  refresh never fails an answer; every recorded id is in the packaged lists, which
  `test_params` checks as a freshness test), `value` as a JSON number (`Decimal`). One
  record per country and attribute; wheat US 2023 has 15.
- `country/all` is the largest answer and has no paging: corn 2023 is 1,875 records from
  125 countries, 275,759 bytes of JSON (`corn_all_2023`); wheat 2023 is 1,845 from 123.
- Release dates (`PSDData_GetDataReleaseInfo`; `models.DataReleaseInfo`): one record per
  country and market year, `commodityCode`, `countryCode`, `marketYear`, `releaseYear`,
  `releaseMonth`, all digit strings; a month, no day, no time, no zone. Wheat: 7,754
  records, 145 countries, market years 1960 to 2026, no world record, about 840 KB.
  `get_release_dates` serves it, filtered by market year and country after the call.
- A data record's `calendarYear`/`month` is the release that last revised it: for wheat
  2023 every one of the 123 countries matches its release record exactly, and the world
  records carry the latest of them (2026-10).
- `meta.vintage` of `get_data` and `get_world_data` is the latest `calendarYear`-`month`
  across the result's records, `"YYYY-MM"` with the month zero-padded: `"2026-07"` for
  wheat US 2023, `"2026-10"` for wheat all countries and world 2023. In every case
  recorded with its release list (wheat 2023: US, all countries, world) it equals the
  release list's record for the same commodity, market year and country, or the latest
  across countries (`test_vintage_equals_the_release_list`); the corn and soybeans
  recordings are internally consistent. So the data tasks make no second call. `None`
  for an empty answer.
- `meta.published_at` is `None` for every task: PSD gives a month, no day, and the
  first of the month would predate the real mid-month release, a look-ahead bias in an
  as-of store.

## Slices (wave 2)

Task-shaped functions in `tasks.py` over the same operations, no wrapper of their own.
They select, order and pivot upstream's records and never change one: no derived
totals, no unit conversion, no gap filling, nothing renamed (ADR-0003).

- `get_balance_sheet(commodity_code, country_code, market_year)`: one request; the
  records of one country-year pivoted into one `BalanceSheet`, `attributes` keyed by the
  packaged attribute name in upstream order. An id whose name the packaged list gives to
  several ids (126 and 173 `"Total Disappearance"`, 133 and 135 `"Fresh Dom.
  Consumption"`) is always keyed with its id (`"Total Disappearance (126)"`), so an id has
  the same key in every answer of a package version; an id the packaged list lacks is
  `"attribute <id>"`; records that one entry each cannot hold (a repeated id, mixed
  keys, two records with the same key) are a `ValidationError`, never merged. A
  reference refresh that renames an attribute or adds an id under an existing name
  changes public keys: a breaking change, recorded in `CHANGELOG.md` when the lists are
  refreshed (conventions §12). Each `BalanceSheetEntry` is a
  projection of the record (`attribute_id`, `unit_id`, `value`, `calendar_year`,
  `month`); units differ per attribute (wheat US: 4, 8 and 26). An empty answer (200
  `[]`) is `NotFoundError`, unlike `get_data`'s empty list: a balance sheet is one record.
- `get_time_series(commodity_code, country_code, attribute_id, start_year, end_year)`:
  one request per market year, oldest first, at the client's pace; `start_year` from
  1960 (the snapshot: "PSD Database has data for most commodities since year 1960");
  at most 100 market years per call (`SERIES_MAX_YEARS`, a self-imposed sanity bound:
  1960 to the current forecast years is about 67 requests, 1960 to 9999 would be
  8,040), no upper bound on `end_year` itself. A future year is expected to answer 404
  like 1900 (not recorded) and costs its request. A year that raises `NoDataForYear`,
  or has no record for the attribute, is absent (no gap filling); an empty series is a
  valid result. Every other error, the gateway's `NOT_FOUND` included, is raised.
- `get_top_countries(commodity_code, market_year, attribute_id, n=10)`: one
  `country/all` request; the attribute's records sorted by `value`, largest first,
  stable, first `n` kept; no unit check, each record carries its own `unit_id`.
  Groupings (`E4`, `T3` Africa, NEC, `X8`, `Z7`, `ZZ`) rank like countries.
  `meta.vintage` is the latest release among every record ranked, not only the `n`
  returned (wheat production 2023: `"2026-10"`; the top five alone `"2026-09"`).
- `get_latest_release(commodity_code)`: one request; the release-list records of the
  newest (`release_year`, `release_month`), `meta.vintage` that release (wheat:
  `"2026-10"`, 146 records); `[]` and `None` for a commodity without releases. The MCP
  server returns at most 200 rows, and a release that adds a market year and revises
  earlier ones can exceed it (the recorded wheat list has 130 more records still on
  2026-09, so September's answer held between 130 and 276);
  `get_release_dates(commodity_code, market_year=..., country_code=...)` returns any
  part of the list in full.

Attribute ids are checked against the packaged list before any call
(`params.validate_attribute_id`, `UnknownCode` with the closest ids).

## Reference data

`scripts/refresh_reference.py` packages the five lists (`commodities`, `countries`,
`regions`, `unitsOfMeasure`, `commodityAttributes`) under `reference/` with provenance
in `reference/README.md`, and regenerates `enums.py` through core's `render_enums`,
committed as the script's `ruff format` and `ruff check --fix` leave it; `--render-only`
regenerates it from the packaged files without a request. The two id lists,
`unitsOfMeasure` and `commodityAttributes`, are the script's `ID_LISTS`; the three
tables, `commodities`, `countries` and `regions`, are its `TABLES`, packaged as JSON
records under upstream's field names like an id list and rendered to no enum; `LISTS`,
the template's value lists, stays empty. Each entry names its upstream operation
verbatim beside its wrapper (`"PSDData_GetCommodities"`, `api.get_commodities`), and
the file's `endpoint` is that operation, never the wrapper's name. Every packaged
list, of either mapping, is in `params.PACKAGED_LISTS`, which the script checks before a
refresh. Refresh policy:
`/refresh-reference-data` inside `/release-prep`, and whenever a validation failure
names a code the package lacks. A refresh that renames an attribute, or adds an id under
an existing name, in `commodityAttributes` changes `get_balance_sheet`'s public keys:
record it in `CHANGELOG.md` as a breaking change (conventions §12).

The `list_*` tasks answer from these files and never call upstream: core's `PackagedList`
builds `meta` (ADR-0022, rule 1), `meta.endpoint` the file's `endpoint`,
`meta.retrieved_at` its `fetched` (the bare date `2026-10-23` reads as 00:00 UTC until the
next refresh writes the full time), `meta.vintage` `None` (upstream gives the lists no
version). Their filters select records client-side, codes and names unchanged, upstream
order kept. Over MCP `list_countries` has a
cap of its own, 300 rows (`tasks.MCP_CAPS`, ADR-0016), so its 251 countries arrive whole;
every other tool keeps the family default, 200 rows or 64 KB. The live tests compare each
packaged list with the live one, the freshness check.

`enums.AttributeId` and `enums.UnitId` are `IntEnum`s, as conventions §3 has it for integer
ids (ADR-0008 amendment, which this package's ruling of 2026-10-23 led to): PSD's ids are
integers in the lists and in every data record, and fidelity to upstream wins. Where
upstream gives two ids the same name, both members carry the id (`TOTAL_DISAPPEARANCE_126`,
`TOTAL_DISAPPEARANCE_173`).
The enums are for lookups and for the wave 2 slice parameters; the models keep the ids
as plain `int` (the NASS pattern), and members compare equal to them.

## Layout

```
src/xippios/usda/psd/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the configured client (base URL, key, rate limit, classify), on core's
                   api.data.gov Gateway (its key, its answers, its quota)
  models.py        pydantic models mirroring upstream payloads (UpstreamModel)
  api/             endpoint wrappers, one module per upstream operation, named after it
                   in snake case without PSDData_ (conventions §2): get_commodities.py
  tasks.py         task functions; __all__ is what the adapters register, but BULK_TASKS,
                   the Python-only ones (none); MCP_CAPS any per-tool result caps
  mcp.py           xippios-usda-psd-mcp entry point
  http.py          FastAPI router
  errors.py        NoDataForYear, PSD's empty 404 for a market year (UnknownCode is core's)
  params.py        packaged lists (PACKAGED_LISTS, read with PackagedList.load;
                   attribute_names()) and the code, year and attribute checks
  enums.py         IntEnums AttributeId, UnitId from the packaged lists; never edited by hand
  reference/       packaged code lists (CSV/JSON) plus README with provenance
scripts/
  refresh_upstream.py    regenerates the docs/upstream/ snapshot, stdlib only, no key
  refresh_reference.py   fetches the packaged lists through api/ and regenerates enums.py;
                         --render-only renders it without a call
tests/
  conftest.py      enables xippios.core.testing.plugin, which keeps the run offline
  fixtures/        recorded responses, <wrapper>/<case>.json, never hand-written; the
                   three over the 256 KiB cap stay under their PSDData_ directories
                   until re-recorded, cut (ADR-0019)
  test_family.py   core's family check, one line: namespace levels, py.typed, __version__,
                   the adapters serving exactly the tasks, task shapes and docstrings, the
                   README status table, the template tag, the core bound
  test_tasks.py    per-task replay tests of the data tasks, MCP and HTTP
  test_lists.py    the list_* tasks: the recorded lists, no call, filters, MCP cap
  test_slices.py   the wave 2 slices: pivot, series, ranking, newest release, checks first
  test_api.py      replay tests for the endpoint wrappers
  test_client.py   classify on recorded error bodies; core's quota policy on the recorded 429
  test_params.py   packaged lists, enums and the code checks
  test_live.py     @pytest.mark.live smoke tests, one per task (14 keyed calls in all), and
                   the template's keyless reachability check
docs/upstream/     documentation snapshot and FETCHED.md
.github/workflows/ ci.yml (the required ci check, with the CHANGELOG and fixture-size steps),
                   publish.yml (the release train: tag, build, PyPI), live.yml (nightly live
                   tests), gates.yml (the merge gates as jobs, off until GATES_CALLER is 1),
                   siblings.yml (the sibling proof of ADR-0006: this wheel beside the
                   siblings under xippios.usda, a visible check the ruleset does not require)
.github/scripts/   check-siblings.sh, which siblings.yml runs; the template's, as is the workflow
.claude/family.md  the family rules, the template's, imported above
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep,
                   adopt-release
```

`src/xippios/` has **no** `__init__.py`: it is a PEP 420 namespace package shared with
`xippios-core` and every other source package, and so is every level
between it and the package (`src/xippios/usda/`). The import path is
`xippios.usda.psd` (ADR-0006).

## Commands

```bash
uv run pytest -m live --tb=short   # needs XIPPIOS_LIVE_TESTS=1 and DATA_GOV_API_KEY

uv run xippios-usda-psd-mcp   # stdio; add --http for streamable HTTP
```

The offline run sends core's placeholder key, with `DATA_GOV_API_KEY` set to it because
`pyproject.toml` names that variable under `xippios_placeholder_key_envs`; the package
keeps no placeholder fixture of its own.

`.github/workflows/live.yml` runs `uv run pytest -m live --tb=short` with
`XIPPIOS_LIVE_TESTS=1` nightly at 01:25 UTC, a time derived from the slug so that sources
sharing a key never start together, and on demand from the Actions tab; pull requests
never run live tests. Only its `uv run pytest -m live --tb=short` step sees the key, from
the org secret `DATA_GOV_API_KEY`.

## USDA FAS PSD Online specifics

- Tests: a replay test goes into the module of its kind, `test_tasks.py` for the data
  tasks, `test_lists.py` for the `list_*` tasks, `test_slices.py` for the slices
  (`/add-endpoint` step 6).
- The quota is the gateway's, not this package's: `_client.py` puts `Gateway.policy`,
  core's one `QuotaPolicy` per process for the shared key, on `config` with
  `gateway.install(...)`, and `classify` asks `gateway.classify` first, which maps a spent
  quota's 429 to `RateLimitError` with `retry_after` (ADR-0009, ADR-0010, ADR-0015). An
  endpoint added here installs no policy of its own; only PSD's own error shapes go into
  `classify`, after the gateway's.
