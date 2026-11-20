# sdk-usda-psd — instructions for Claude Code

`xippios-usda-psd` wraps USDA FAS PSD Online as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file holds what an agent needs to work on
the package: what it wraps, its layout, its commands and its code rules. The documents it
follows, sdk-core's conventions among them, are listed under
[`## Documents` in the README](README.md#documents); read them before you change a file.

## What this package wraps

| | |
| --- | --- |
| Upstream | USDA FAS PSD Online, https://apps.fas.usda.gov/psdonline/ |
| API base URL | `https://api.fas.usda.gov` |
| Documentation | https://apps.fas.usda.gov/opendatawebV2/, snapshotted in `docs/upstream/` |
| Credentials | `DATA_GOV_API_KEY` from the environment, sent as the `X-Api-Key` header by `xippios.core.data_gov`'s `Gateway` (`_client.auth` is `gateway.auth`); the key is api.data.gov's, shared by every package that reads it. sdk-core ADR-0032: one key variable per issuer when one key serves several sources, so every source reached through api.data.gov (`usda-psd`, `usda-esr`, `usda-gats`) reads `DATA_GOV_API_KEY`, and one key is one gateway quota |
| Rate limit | sdk-core ADR-0033, decisions 1–5. Pace: 60 requests per minute, burst 1 (`RateLimit(per_minute=60, burst=1)` in `_client.py`, enforced client-side): a self-imposed pace, upstream documents none (the snapshot names no limit). Quota: api.data.gov's 1,000 requests per rolling hour per key, reported in `x-ratelimit-limit` / `x-ratelimit-remaining` (the hourly quota, not a pace) and shared by every package and process using the same `DATA_GOV_API_KEY`; it may be spent, it is not pre-rationed. The quota is the gateway's: `Gateway.policy` of `xippios.core.data_gov`, one `QuotaPolicy` per process for the key, which `_client.py` installs with `gateway.install` (sdk-core ADR-0032, sdk-core ADR-0037), keeps the snapshot from every answer from the wire, never a cache hit's, and gates: once the quota is spent the next request waits it out inside the call, logged, when that is within the policy's `pause_cap` (30 s by default), and otherwise raises `RateLimitError` with `retry_after` without sending, a refusal that speaks for `api.data.gov` (its `source`). The wait counts from the last answer: a 429's `Retry-After`, else the policy's `window` of one hour (the gateway sends no reset header, and the 200 that leaves `remaining` at 0 no `Retry-After`). `gateway.classify`, which `classify` asks first, maps the 429 to `RateLimitError` with `retry_after` the wait the policy keeps the quota spent for, from `Retry-After` (recorded: 3151 s, `over_rate_limit.json`), else 3600 s, and core shapes its retries from that: a wait beyond `RetryPolicy.backoff_max` is raised after one request. In offline tests core's pytest plugin bypasses the limiter and the quota policy and forgets the snapshot around each test; a test that asserts a wait or a refusal is marked `rate_limited` |
| Write tools | no, this package is read-only |

The snapshot listed in `docs/upstream/FETCHED.md` is the reference for names, parameters and
semantics; a wrapper is never written from memory of the API.

## Layout

```
src/xippios/usda/psd/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the configured client (base URL, key, rate limit), ENV_VARS and classify,
                   on core's api.data.gov Gateway (its key, its answers, its quota, and
                   NoDataForYear on DATA_PATH)
  models.py        pydantic models mirroring upstream payloads (UpstreamModel); by the
                   family's precedent also an enumeration written by hand, for a value set
                   upstream documents and no packaged list renders
  api/             endpoint wrappers, one module per upstream operation, named after it
                   in snake case without PSDData_ (conventions §2): get_commodities.py
  tasks.py         task functions; __all__ is what the adapters register, but BULK_TASKS,
                   the Python-only ones (none); MCP_CAPS any per-tool result caps
  mcp.py           xippios-usda-psd-mcp entry point: build() the tool set, server
  http.py          FastAPI router
  params.py        packaged lists (PACKAGED_LISTS, read with PackagedList.load;
                   attribute_names()) and the code, year and attribute checks
  enums.py         IntEnums AttributeId, UnitId from the packaged lists; never edited by hand
  reference/       packaged code lists (CSV/JSON) plus README with provenance
scripts/
  refresh_upstream.py    regenerates the docs/upstream/ snapshot, stdlib only, no key
  refresh_reference.py   fetches the packaged lists through api/ and regenerates enums.py;
                         --render-only renders it without a call
  adr_index.py           writes docs/adr.md and docs/adr.json from the records in docs/adr/;
                         --check fails while either is stale
tests/
  conftest.py      enables xippios.core.testing.plugin, which keeps the run offline
  fixtures/        recorded responses, <wrapper>/<case>.json, never hand-written; an
                   answer over the 256 KiB cap is recorded cut (sdk-core ADR-0040, decision 5)
  test_family.py   core's family check, one line: namespace levels, py.typed, __version__,
                   the adapters serving exactly the tasks, task shapes and docstrings, the
                   README status table, the template tag, the core bound
  test_tasks.py    per-task replay tests of the data tasks, MCP and HTTP
  test_lists.py    the list_* tasks: the recorded lists, no call, filters, MCP cap
  test_slices.py   the slices: pivot, series, ranking, newest release, checks first
  test_api.py      replay tests for the endpoint wrappers
  test_client.py   classify on recorded error bodies; core's quota policy on the recorded 429
  test_params.py   packaged lists, enums and the code checks
  test_refresh_upstream.py   the capture script's FETCHED.md and writing, offline: the
                   row of OBSERVED.md
  test_live.py     @pytest.mark.live smoke tests, one per task and one more each for the
                   new arguments of get_time_series, get_top_countries, get_release_dates
                   and get_latest_release (18 keyed calls in all), and the template's
                   keyless reachability check
docs/
  upstream/        documentation snapshot and FETCHED.md
  adr/             this package's design decisions, one NNNN-<slug>.md record each, laid
                   out in its README.md
  adr.md           the index of the decisions, written by scripts/adr_index.py, never by hand
  adr.json         the same index, for machines
  reports/         dated reports, the evidence a decision cites, laid out in its README.md
changelog/         the next release's changelog entries, one fragment per change, laid out
                   in its README.md
CHANGELOG.md       the releases, each section assembled from the fragments
.github/workflows/ ci.yml (the required ci check, with the changelog and fixture-size steps),
                   publish.yml (the release train: tag, build, PyPI), live.yml (nightly live
                   tests), organization.yml (the organization's checks from xippios/.github:
                   conventions, a review of a pull request against the documents the README
                   lists, and adr-index, which runs scripts/adr_index.py --check),
                   siblings.yml (the sibling proof of sdk-core ADR-0006: this wheel beside the
                   siblings under xippios.usda, a visible check the ruleset does not require)
.github/scripts/   check-siblings.sh, which siblings.yml runs; the template's, as is the workflow
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep
```

The import path is `xippios.usda.psd` (sdk-core ADR-0006); `src/xippios/` is a
namespace package, and so is `src/xippios/usda/`, the provider level.
Where the API's operation ids repeat across its services, `api/` keeps one module per service
instead, named after the service, and this Layout says so (conventions §2).

## Commands

```bash
uv sync --all-extras
uv run pytest                      # offline, replays the fixtures
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit run --all-files
python3 scripts/adr_index.py --check   # the index matches the records in docs/adr/
uv run pytest -m live --tb=short --assert=plain   # needs XIPPIOS_LIVE_TESTS=1, DATA_GOV_API_KEY

uv run xippios-usda-psd-mcp   # stdio; add --http for streamable HTTP
```

`uv run pytest` is offline: core's plugin refuses the network and skips the rate limiter's
waits in every test not marked `live` (conventions §10, sdk-core ADR-0035). A test that
asserts a limiter wait or a quota pause is marked `rate_limited`, one that must reach the
network `network`.
It sends the key's placeholder, with `DATA_GOV_API_KEY` set to it because
`pyproject.toml` names that variable under `xippios_placeholder_key_envs`; the package
keeps no placeholder fixture of its own.

`.github/workflows/live.yml` runs the live tests nightly at 01:25 UTC, a time derived from
the slug so that sources sharing a key never start together, and on demand; a pull request
never runs them. Only its `uv run pytest -m live --tb=short --assert=plain` step sees the
key, from the org secret `DATA_GOV_API_KEY`.
Every live run takes `--tb=short --assert=plain`, since the log of `live.yml` is public:
the first keeps a failing test's frame arguments out of it, a raw upstream payload among
them, and the second the values a failed `assert` compares. A live test asserts on shapes
and counts, never on a raw payload.

## Code rules

- Three layers (sdk-core ADR-0001, conventions §2): endpoint wrappers in `api/`, task
  functions in `tasks.py`, adapters in `mcp.py` and `http.py`. The adapters register
  `tasks.__all__` and call only tasks, the tasks call only wrappers and reference data, and
  a wrapper returns models.
- Upstream's documented error shapes go into `classify` in `_client.py`, once, and an error
  class of the package's own into `errors.py`; a wrapper never inspects a status code
  (conventions §5, §6).
- One limiter paces each host the package sends to (conventions §2, §6). A second base URL
  on the host of the API base URL goes through the one `client` of `_client.py` by its
  absolute URL, and `classify`'s path checks name both bases. An origin or mirror that the
  publisher runs itself, where its canonical host refuses automated requests, takes that
  host's pace through the same client, and `docs/upstream/` names both hosts; a mirror that
  anyone else runs is never sent to. A host that a dependency sends to is reached through
  the dependency's tasks alone. Any other host gets a client of its own in `_client.py`,
  its base URL and its `RateLimit` beside the first's, and a row of its own in the table
  under What this package wraps, with its pace and where the pace comes from.
- A change brings its tests, written before the code, and passes the offline checks above;
  its changelog entry is a fragment under `changelog/`, one file holding its bullet, as
  `changelog/README.md` lays it out (conventions §12). Commit subjects follow Conventional
  Commits (conventions §13): the rule binds a pull request's own commits, not the commit
  that lands the pull request on `main`, whose subject GitHub writes.
- `ruff` leaves `docs/` and `.claude/` alone (`pyproject.toml`), so the upstream snapshot
  keeps its bytes: never reformat it.
- A convention that seems wrong is followed anyway and said in the pull request; changing
  it is a change of sdk-core's `docs/conventions.md` with an ADR.

## Never

- Never hand-write a fixture, and never commit one without grepping it for key patterns
  (conventions §10).
- Never read or print `.envrc`, `.env`, the credential variable of this package,
  `DATA_GOV_API_KEY`, or any variable ending in `_API_KEY`, `_TOKEN` or
  `_SECRET`.
- Never write a key, a token or another credential into a file or a commit.
- Never put logic in `mcp.py` or `http.py`, and never add a route or a tool by hand: the
  adapters register `tasks.__all__` (sdk-core ADR-0001).
- Never rename or re-map an upstream concept to another source's (sdk-core ADR-0028).
- Never return a documented personal identifier in a task's projection, echo one in
  `meta.request`, or commit one in a fixture (sdk-core ADR-0017).
- Never edit `docs/upstream/` by hand but `docs/upstream/OBSERVED.md`, the notes on what
  upstream does but never documents: `/refresh-upstream` fetches the rest, and the pull
  request shows its diff (conventions §3).
- Never add `src/xippios/__init__.py`, nor an `__init__.py` at a level between it and the
  package (sdk-core ADR-0006).
- Never push a tag by hand: a release's tag comes from `publish.yml` alone (conventions §12).

## Template updates

This repository is generated from sdk-template, at the tag `.copier-answers.yml` records. A
template release reaches it in a pull request of its own, with
`uvx --from 'copier>=9.19' copier update --defaults --vcs-ref=<tag>` (conventions §15): the
update renders the template's files again and never overwrites the files this package
fills, `__init__.py`, `_client.py`, `errors.py`, `models.py`, `api/`, `parse/`, `tasks.py`,
`tasks_write.py`, `params.py`, `enums.py`, `reference/`, `scripts/refresh_reference.py`,
`scripts/refresh_upstream.py`, `tests/test_tasks.py`, `tests/test_live.py`,
`tests/fixtures/`, `docs/upstream/`, `docs/adr.md`, `docs/adr.json`, `README.md`,
`CHANGELOG.md` and `CLAUDE.md`. sdk-template's
[CHANGELOG](https://github.com/xippios/sdk-template/blob/main/CHANGELOG.md) says, per
release, what to port into those by hand in the same pull request.

## When something is unclear

Prefer the smallest change that satisfies the documents the README lists, state the
assumption in the pull request's description, and stop rather than guess at upstream
semantics or the shape of the public API.

## Upstream behaviour established by fixtures

The snapshot types every response as `object`, so these facts come from the answers
recorded on 2026-10-23 under `tests/fixtures/`, and the three re-recorded cut on
2026-10-28 (sdk-core ADR-0040, decision 5); `_client.classify` maps them once. A fact of a whole
answer the cut fixtures no longer hold is dated 2026-10-23; those whole recordings are in
commit `07b88ad` on `main`.

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
  mapped by core's gateway, given `_client.DATA_PATH`, to `NoDataForYear` of
  `xippios.core.data_gov`, a `NotFoundError` (only that answer on a data path: an empty
  404 elsewhere or the gateway's `NOT_FOUND` stays a plain `NotFoundError`).
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
- `country/all` is the largest answer and has no paging: corn 2023 is 1,875 records,
  275,759 bytes of JSON (`corn_all_2023`), wheat 2023 1,845 records, 271,470 bytes, both
  ordered by country code; the fixtures are cut at 200,000 bytes and keep the countries
  from AF to RH (corn) and to RS (wheat), the whole sizes in their `original_count` and
  `original_bytes`. On 2026-10-23 the whole answers held 125 and 123 countries.
- Release dates (`PSDData_GetDataReleaseInfo`; `models.DataReleaseInfo`): one record per
  country and market year, `commodityCode`, `countryCode`, `marketYear`, `releaseYear`,
  `releaseMonth`, all digit strings; a month, no day, no time, no zone. Wheat: 7,754
  records, 837,433 bytes (`original_count`, `original_bytes`), ordered by market year,
  oldest first (within a year by country code on 2026-10-28, in another order on
  2026-10-23), so the cut fixture keeps market years 1960 to 1978, whose newest release
  is 2024-02. The whole list of 2026-10-23 held 145 countries, market years 1960 to
  2026 and no world record. `get_release_dates` serves it, filtered by market year,
  country and `since` after the call.
- A data record's `calendarYear`/`month` is the release that last revised it: for wheat
  2023 every one of the 123 countries matched its release record exactly, and the world
  records carried the latest of them (2026-10), in the whole answers of 2026-10-23.
- `meta.vintage` of `get_data` and `get_world_data` is the latest `calendarYear`-`month`
  across the result's records, `"YYYY-MM"` with the month zero-padded: `"2026-07"` for
  wheat US 2023, `"2026-10"` for wheat all countries and world 2023. In every case
  recorded with its whole release list (wheat 2023: US, all countries, world, on
  2026-10-23) it equals the release list's record for the same commodity, market year
  and country, or the latest across countries; the corn and soybeans recordings are
  internally consistent. So the data tasks make no second call. The cut release list
  ends at market year 1978, so no replay test re-checks this on 2023 any more; the
  whole recordings of commit `07b88ad` show it. `None` for an empty answer.
- `meta.published_at` is `None` for every task: PSD gives a month, no day, and the
  first of the month would predate the real mid-month release, a look-ahead bias in an
  as-of store.

## Slices

Task-shaped functions in `tasks.py` over the same operations, no wrapper of their own.
They select, order and pivot upstream's records and never change one: no derived
totals, no unit conversion, no gap filling, nothing renamed (sdk-core ADR-0028).

- `get_balance_sheet(commodity_code, country_code, market_year)`: one request; the
  records of one country-year pivoted into one `BalanceSheet`, `attributes` keyed by the
  packaged attribute name in upstream order. An id whose name the packaged list gives to
  several ids (126 and 173 `"Total Disappearance"`, 133 and 135 `"Fresh Dom.
  Consumption"`) is always keyed with its id (`"Total Disappearance (126)"`), so an id has
  the same key in every answer of a package version; an id the packaged list lacks is
  `"attribute <id>"`; records that one entry each cannot hold (a repeated id, mixed
  keys, two records with the same key) are a `ValidationError`, never merged. A
  reference refresh that renames an attribute or adds an id under an existing name
  changes public keys: a breaking change, recorded in a `breaking` fragment under
  `changelog/` when the lists are refreshed (conventions §12). Each `BalanceSheetEntry` is a
  projection of the record (`attribute_id`, `unit_id`, `value`, `calendar_year`,
  `month`); units differ per attribute (wheat US: 4, 8 and 26). An empty answer (200
  `[]`) is `NotFoundError`, unlike `get_data`'s empty list: a balance sheet is one record.
- `get_time_series(commodity_code, country_code, start_year, end_year, attribute_id=None)`:
  `attribute_id` an id, a list of ids or, omitted, every attribute; every id is checked
  before the first request and an empty list is refused; records as upstream sent them,
  ordered by market year and within a year in upstream's order; `meta.request` carries
  `attribute_id` as given (the id or the list) and leaves it out when omitted. Since the
  parameter takes a list, the HTTP route is a `POST` with a JSON body (conventions §9).
  One request per market year, oldest first, at the client's pace; `start_year` from
  1960 (the snapshot: "PSD Database has data for most commodities since year 1960");
  at most 100 market years per call (`SERIES_MAX_YEARS`, a self-imposed sanity bound:
  1960 to the current forecast years is about 67 requests, 1960 to 9999 would be
  8,040), no upper bound on `end_year` itself. A future year is expected to answer 404
  like 1900 (not recorded) and costs its request. A year that raises `NoDataForYear`,
  or has no record for the attributes, is absent (no gap filling); an empty series is a
  valid result. Every other error, the gateway's `NOT_FOUND` included, is raised. Over
  MCP a cut series' note names `attribute_id`, `start_year` and `end_year`
  (`tasks.MCP_CAPS`).
- `get_top_countries(commodity_code, market_year, attribute_id, n=10, region_code=None,
  exclude_groupings=False)`: one `country/all` request; the attribute's records sorted
  by `value`, largest first, stable, first `n` kept; no unit check, each record carries
  its own `unit_id`. By default PSD's groupings rank like countries;
  `exclude_groupings=True` leaves out `tasks.GROUPINGS`, the eight aggregates of the
  packaged countries list (`E4` European Union, `E2` EU-15, `E3` EU-25, `C1` Caribbean
  Basin, `T3` Africa, NEC, `X8` Southern Asia NEC, `Z7` Other Pacific Islands, NEC, `ZZ`
  Other), named by hand, never inferred from names. `region_code` keeps the records
  whose country the packaged countries list puts in that region (the data records
  carry none), checked before the call against the `regionCode` values the packaged
  countries carry, `R15` included (`params.validate_region_code`); `R00` (World), in the
  regions list but carried by no country, is refused with a hint that the world total
  is `get_world_data`'s. `meta.vintage` is the latest release among every record
  ranked, after both apply, not only the `n` returned (wheat production 2023:
  `"2026-10"`; the top five alone `"2026-09"`; South America, `R04`, `"2026-09"`).
- `get_latest_release(commodity_code, since=None)`: one request; the release-list
  records of the newest (`release_year`, `release_month`), `meta.vintage` that release
  (wheat on 2026-10-23: `"2026-10"`, 146 records); `[]` and `None` for a commodity
  without releases. `since`, a release month `"YYYY-MM"` as `meta.vintage` writes it
  (`params.validate_since`), returns `[]` when the newest release is not later than it,
  `meta.vintage` still naming that release, so a poll with the stored vintage learns
  that nothing newer exists; `get_release_dates(..., since=...)` keeps the records of
  releases strictly after it. The MCP server returns at most 200 rows, and a release
  that adds a market year and revises earlier ones can exceed it (the wheat list of
  2026-10-23 had 130 more records still on 2026-09, so September's answer held between
  130 and 276); `get_release_dates(commodity_code, market_year=..., country_code=...,
  since=...)` returns any part of the list in full.

Attribute ids and region codes are checked against the packaged lists before any call
(`params.validate_attribute_id`, `params.validate_region_code`, `UnknownCode` with the
closest), and a release month against its form (`params.validate_since`,
`InvalidRequestError`).

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
record it in a fragment of the group `breaking` under `changelog/` (conventions §12).

The `list_*` tasks answer from these files and never call upstream: core's `PackagedList`
builds `meta` (sdk-core ADR-0041, decision 1), `meta.endpoint` the file's `endpoint`,
`meta.retrieved_at` its `fetched`, the UTC time of the list's fetch to the second as
`PackagedList.write` writes it (the refresh of 2026-10-28), `meta.vintage` `None`
(upstream gives the lists no version). Their filters select records client-side, codes
and names unchanged, upstream order kept. Over MCP `list_countries` has a cap of its own,
300 rows (`tasks.MCP_CAPS`, sdk-core ADR-0038), so its 251 countries arrive whole;
`get_data`, `get_release_dates` and `get_time_series` keep the family's limits, 200 rows
or 64 KB, with a note naming their filters (`country_code`; `market_year`,
`country_code`, `since`; `attribute_id`, `start_year`, `end_year`); every other tool
keeps the family default with core's note. The live tests compare each
packaged list with the live one, the freshness check.

`enums.AttributeId` and `enums.UnitId` are `IntEnum`s, as conventions §3 has it for integer
ids (sdk-core ADR-0031, decision 6, the rule that decision 5 of this package's
https://github.com/xippios/sdk-usda-psd/pull/3 led to): PSD's ids are integers in the lists
and in every data record, and fidelity to upstream wins. Where upstream gives two ids the
same name, both members carry the id (`TOTAL_DISAPPEARANCE_126`, `TOTAL_DISAPPEARANCE_173`).
The enums are for lookups and for the slices' parameters; the models keep the ids
as plain `int` (the NASS pattern), and members compare equal to them.

## USDA FAS PSD Online specifics

- Tests: a replay test goes into the module of its kind, `test_tasks.py` for the data
  tasks, `test_lists.py` for the `list_*` tasks, `test_slices.py` for the slices
  (`/add-endpoint` step 6).
- The quota is the gateway's, not this package's: `_client.py` puts `Gateway.policy`,
  core's one `QuotaPolicy` per process for the shared key, on `config` with
  `gateway.install(...)`, and `classify` asks `gateway.classify` first, which maps a spent
  quota's 429 to `RateLimitError` with `retry_after` (sdk-core ADR-0032,
  sdk-core ADR-0033, sdk-core ADR-0037). An endpoint added here installs no policy of its
  own; only PSD's own error shapes go into `classify`, after the gateway's.
- The reference guard: `test_balance_sheet_keys_of_every_packaged_attribute_are_pinned`
  in `tests/test_slices.py` writes out the key `get_balance_sheet` gives each packaged
  attribute id; when a reference refresh fails it, the refresh PR updates the mapping and
  records every changed or newly suffixed key in a `breaking` fragment under `changelog/`
  (conventions §12).
