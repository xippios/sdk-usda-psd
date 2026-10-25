# sdk-usda-psd — instructions for Claude Code

`xippios-usda-psd` wraps USDA FAS PSD Online as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file is the contract for every session
that works here; the family rules it points to apply as well.

## What this package wraps

| | |
| --- | --- |
| Upstream | USDA FAS PSD Online, https://apps.fas.usda.gov/psdonline/ |
| API base URL | `https://api.fas.usda.gov` |
| Documentation | https://apps.fas.usda.gov/opendatawebV2/, snapshotted in `docs/upstream/` |
| Credentials | `DATA_GOV_API_KEY` from the environment, sent as the `X-Api-Key` header. ADR-0009: one key variable per issuer when one key serves several sources, so every source reached through api.data.gov (`usda-psd`, `usda-esr`, `usda-gats`) reads `DATA_GOV_API_KEY`, and one key is one gateway quota |
| Rate limit | ADR-0010, decisions 1–5. Pace: 60 requests per minute, burst 1 (`RateLimit(per_minute=60, burst=1)` in `_client.py`, enforced client-side): a self-imposed pace, upstream documents none (the snapshot names no limit). Quota: api.data.gov's 1,000 requests per rolling hour per key, reported in `x-ratelimit-limit` / `x-ratelimit-remaining` (the hourly quota, not a pace) and shared by every package and process using the same `DATA_GOV_API_KEY`; it may be spent, it is not pre-rationed. Core's `QuotaPolicy` (`_client.policy`, ADR-0015) keeps the snapshot from every answer from the wire, never a cache hit's, and gates: once the quota is spent the next request waits it out inside the call, logged, when that is within `RetryPolicy.backoff_max` (30 s by default), and otherwise raises `RateLimitError` with `retry_after` without sending. The wait counts from the last answer: a 429's `Retry-After`, else the policy's `window` of one hour (the gateway sends no reset header, and the 200 that leaves `remaining` at 0 no `Retry-After`). `classify` maps the 429 to `RateLimitError` with `retry_after` from `Retry-After` (recorded: 3151 s, `over_rate_limit.json`), else 3600 s, and core shapes its retries from that: a wait beyond `backoff_max` is raised after one request. In offline tests core's pytest plugin bypasses the limiter and the quota policy and forgets the snapshot around each test; a test that asserts a wait or a refusal is marked `rate_limited` |
| Write tools | no, this package is read-only |

The snapshot in `docs/upstream/` is the reference for names, parameters and semantics.
If it is empty or stale, run `/refresh-upstream` first and review the diff. Never write a
wrapper from memory of the API.

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
  recorded from a fresh process (`PSDData_GetCommodities/over_rate_limit.json`): HTTP 429,
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
  changes public keys: a breaking change (conventions §12), which
  `/refresh-reference-data` records in the CHANGELOG. Each `BalanceSheetEntry` is a
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
in `reference/README.md`, and regenerates `enums.py` through core's `render_int_enums`,
committed as rendered; `--render-only` regenerates it from the packaged files without a
request. Refresh policy:
`/refresh-reference-data` inside `/release-prep`, and whenever a validation failure
names a code the package lacks.

The `list_*` tasks answer from these files and never call upstream: `meta.endpoint` is
the file's `endpoint`, `meta.vintage` its `fetched` date (upstream gives the lists no
version), `meta.retrieved_at` when the task answered. Their filters select records
client-side, codes and names unchanged, upstream order kept. Over MCP `list_countries` has a
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

## Read first, in this order

1. `docs/upstream/FETCHED.md` and the files it lists: what the upstream actually offers
2. The family conventions: `../sdk-core/docs/conventions.md` and `../sdk-core/docs/adr/`
   (also at https://github.com/xippios/sdk-core/tree/main/docs)
3. `../sdk-core/docs/definition-of-done.md`: what a PR must satisfy
4. The family file `../CLAUDE.md`
5. When a new core minor or template release comes: conventions §15, the adoption
   checklist, which `/adopt-release` walks

## The one rule: three layers (ADR-0001)

```
api/<operation>.py   one async function per upstream operation, upstream names, returns models
tasks.py             the public API: composes wrappers, returns Result[T], sync facade via sync()
mcp.py  http.py      adapters: register tasks.__all__, nothing else. Never edited to add an endpoint.
```

Adapters call only task functions. Tasks call only endpoint wrappers and reference
data. If logic appears in `mcp.py` or `http.py`, it belongs in `tasks.py`.

## Layout

```
src/xippios/usda/psd/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the configured client (base URL, key, rate limit, classify, quota)
  models.py        pydantic models mirroring upstream payloads (UpstreamModel)
  api/             endpoint wrappers, one module per upstream operation
  tasks.py         task functions; __all__ is what the adapters register, MCP_CAPS any
                   per-tool result caps
  mcp.py           xippios-usda-psd-mcp entry point
  http.py          FastAPI router
  errors.py        UnknownCode (a code or attribute id the packaged lists lack), NoDataForYear
  params.py        packaged lists (PACKAGED_LISTS, packaged_values(), attribute_names()) and checks
  enums.py         IntEnums AttributeId, UnitId from the packaged lists; never edited by hand
  reference/       packaged code lists (CSV/JSON) plus README with provenance
scripts/
  refresh_upstream.py    regenerates the docs/upstream/ snapshot, stdlib only, no key
  refresh_reference.py   fetches the packaged lists through api/ and regenerates enums.py
  check-siblings.sh      this wheel and xippios-usda-nass share xippios.usda (workflow siblings.yml)
tests/
  conftest.py      enables xippios.core.testing.plugin, which keeps the run offline
  fixtures/        recorded responses, <endpoint>/<case>.json, never hand-written
  test_tasks.py    structural checks on every task plus per-task replay tests
  test_lists.py    the list_* tasks: the recorded lists, no call, filters, MCP cap
  test_slices.py   the wave 2 slices: pivot, series, ranking, newest release, checks first
  test_api.py      replay tests for the endpoint wrappers
  test_client.py   classify on recorded error bodies; core's quota policy on the recorded 429
  test_params.py   packaged lists, enums and the code checks
  test_adapters.py the adapters expose exactly tasks.__all__
  test_layout.py   namespace levels stay empty; py.typed ships
  test_live.py     @pytest.mark.live smoke tests, one per task (14 keyed calls in all)
docs/upstream/     documentation snapshot and FETCHED.md
.github/workflows/ ci.yml (the required ci check), publish.yml (tag to PyPI), live.yml (nightly live tests),
                   siblings.yml (scripts/check-siblings.sh, this package's own)
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep,
                   adopt-release
```

`src/xippios/` has **no** `__init__.py`: it is a PEP 420 namespace package shared with
`xippios-core` and every other source package, and so is every level
between it and the package (`src/xippios/usda/`).
Never add one; `tests/test_layout.py` fails if it appears. The import path is
`xippios.usda.psd` (ADR-0006).

## How to add an endpoint

Run `/add-endpoint <upstream operation>`. In short:

1. Read the operation in `docs/upstream/`. Names, parameters and semantics come from
   there, snake_cased, nothing renamed, nothing normalised across sources.
2. `models.py`: an `UpstreamModel` per payload object; dates, numbers and enums typed.
3. `api/<operation>.py`: one async wrapper that calls `_client.client` and returns
   models through `xippios.core.parse`.
4. `tasks.py`: an async task that composes wrappers and returns `Result[T]` with full
   `ResultMeta` (source, endpoint, request parameters, `published_at`/`vintage` when the
   upstream gives them). Derive the sync one with `sync()`, add its name to `__all__`,
   re-export it from `__init__.py`. What it returns leaves out documented personal
   identifiers (`ssn`, `iban` and their like) unless it fetches them deliberately and
   says so, and a write task does not echo one in `meta.request` (ADR-0017).
5. Docstring for agents: one sentence, then `Args:` with examples of valid values for
   every parameter. The MCP tool description and the OpenAPI summary come from it.
6. `/record-fixture` for at least one case, a replay test in the matching test module
   (`test_tasks.py` for the data tasks, `test_lists.py` for the `list_*` tasks,
   `test_slices.py` for the slices) that also calls the tool end to end with
   `xippios.core.testing.mcp_call` (and compares what was sent through
   `sent_urls(route)`, never a request from `route.calls`), a live smoke test in
   `test_live.py`.
7. `CHANGELOG.md` under Unreleased, README status table, then the full check suite.

Reference lookups (commodities, countries, attributes) are tasks too, named
`list_<thing>`, so agents can form valid calls; one whose whole list an agent needs and
the default result cap (200 rows or 64 KB) would cut gets a cap of its own in `MCP_CAPS`
in `tasks.py`, which `mcp.py` passes through (ADR-0016). A task-shaped function that returns a
subset of an upstream record builds its model with `UpstreamModel.project`; nothing is
renamed or computed, parsing a value (`parse_decimal`) is the only override. Upstream's
documented error shapes go into `ClientConfig.classify` in `_client.py`, once; wrappers
use `client.get_json` and never inspect status codes. An upstream that reports an hourly
or daily quota gets one `QuotaPolicy` installed on `config` there, as the commented block
in `_client.py` shows, and `classify` maps its answer to a spent quota to
`RateLimitError` with `retry_after` (ADR-0010, ADR-0015).

## How to record a fixture

Run `/record-fixture <endpoint> <case> <parameters>`. It performs one live request
through the real client with `xippios.core.testing.record_sync` and writes
`tests/fixtures/<endpoint>/<case>.json` with credentials scrubbed. Grep the file for
key patterns, and for the personal identifiers the package keeps out of its projections
(ADR-0017), before committing. Fixtures are never typed in by hand.

## Commands

```bash
uv sync --all-extras
uv run pytest                      # offline, replays fixtures
uv run pytest -m live              # needs XIPPIOS_LIVE_TESTS=1 and DATA_GOV_API_KEY
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit run --all-files
uv run xippios-usda-psd-mcp   # stdio; add --http for streamable HTTP
```

The offline run is core's plugin's (ADR-0013): in every test not marked `live` it refuses
the network and skips the rate limiter's waits, and the key sent is its placeholder,
with `DATA_GOV_API_KEY` set to it because `pyproject.toml` names that variable under
`xippios_placeholder_key_envs`; the package keeps no placeholder fixture of its own.
A test that asserts a limiter wait or a quota pause is marked `rate_limited`, one that
must reach the network `network`.

`.github/workflows/live.yml` runs `uv run pytest -m live` with `XIPPIOS_LIVE_TESTS=1`
nightly at 01:25 UTC, a time derived from the slug so that sources sharing a key never
start together, and on demand from the Actions tab; pull requests never run live tests.
Only its `uv run pytest -m live` step sees the key, from the org secret `DATA_GOV_API_KEY`.

## Workflow rules

- Branch from `main` as `feature/<topic>`, `fix/<topic>`, `chore/<topic>` or `docs/<topic>`.
  Never commit to `main`.
- Commit small, with Conventional Commits messages (`feat(tasks): add get_balance_sheet`).
- Open the PR with `gh pr create`; the body is the definition-of-done checklist from
  `.github/PULL_REQUEST_TEMPLATE.md`, ticked honestly, with assumptions listed.
- `ruff` leaves `docs/` alone; never reformat the upstream snapshot.
- Template and core updates: a new sdk-template release, and the core minor it carries,
  arrive in one adoption PR, `chore/template-update-<tag>`, before the next release
  (conventions §15); `/adopt-release <tag>` walks it, and it auto-merges after the
  reviewer's `ready`. `uvx copier update` re-renders the files the template owns
  (`tests/conftest.py`, `tests/test_layout.py` and `tests/test_adapters.py` among them;
  answers are in `.copier-answers.yml`) and never overwrites the files this package fills:
  `__init__.py`, `_client.py`, `models.py`, `api/`, `tasks.py`, `tasks_write.py`,
  `params.py`, `enums.py`, `reference/`, `scripts/`, `tests/test_tasks.py`,
  `tests/test_tasks_write.py`, `tests/test_live.py`, `tests/fixtures/`, `docs/upstream/`,
  `README.md` and `CHANGELOG.md`. Template changes to those are listed per release under
  "Hand-apply" in sdk-template's
  [CHANGELOG](https://github.com/xippios/sdk-template/blob/main/CHANGELOG.md); port them
  by hand in the same PR.
- If a convention seems wrong, say so in the PR and follow it anyway; changing it is a
  PR against `sdk-core/docs/conventions.md` plus an ADR.

## Never

- Never hand-write a fixture, and never commit one without grepping for key patterns.
- Never read or print `.envrc`, `.env`, or any variable ending in `_API_KEY`.
- Never write a key into a file or a commit.
- Never put logic in `mcp.py` or `http.py`; never add a route or tool by hand.
- Never rename or re-map an upstream concept to another source's (ADR-0003).
- Never return a documented personal identifier in a task's projection, echo one in
  `meta.request`, or commit one in a fixture (ADR-0017).
- Never edit `docs/upstream/` by hand; `/refresh-upstream` fetches, a PR reviews.
- Never add `src/xippios/__init__.py` or `src/xippios/usda/__init__.py`, the provider level.
- Never tag, merge, release, force-push, or touch `gh secret`. Those are human actions;
  the one exception is enabling auto-merge on a `chore/template-update*` or
  `chore/release-*` PR after the reviewer's `ready` (ADR-0018).

## When something is unclear

Prefer the smallest change that satisfies the documents above, state the assumption in
the PR description, and stop rather than guess at upstream semantics or public API shape.
