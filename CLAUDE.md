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
| Credentials | `DATA_GOV_API_KEY` from the environment, sent as the `X-Api-Key` header |
| Rate limit | 60 requests per minute, one at a time (`RateLimit(per_minute=60, burst=1)` in `_client.py`), self-imposed: the snapshot documents no limit. The api.data.gov gateway enforces 1,000 requests per rolling hour per key, observed in `x-ratelimit-limit` / `x-ratelimit-remaining` and shared by every package using the same `DATA_GOV_API_KEY`. A 429 raises `RateLimitError` with `retry_after` from `Retry-After`, else 3600 s. Once `x-ratelimit-remaining` reaches 0 the next request never fires into a 429 (`QuotaAwareClient`): it waits the quota out when the wait is within the client's `RetryPolicy.backoff_max` (30 s by default, the same bound core uses for a `Retry-After`), otherwise it raises `RateLimitError` with `retry_after` without sending; `quota()` reports what is left |
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
- Market year without data (`commodity/0410000/country/US/year/1900`): HTTP 404 with an
  empty `text/plain` body, mapped to `NotFoundError`.
- Invalid key: HTTP 403 `{"error": {"code": "API_KEY_INVALID", "message": "An invalid
  api_key was supplied. Get one at https://api.fas.usda.gov:443"}}`, no quota headers;
  mapped to `AuthError` naming the code and `DATA_GOV_API_KEY`. The other documented
  `API_KEY_*` codes map the same way. The gateway's `NOT_FOUND` 404 is `NotFoundError`.
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
  as integers (every recorded id is in the packaged lists, so they are typed with the
  enums), `value` as a JSON number (`Decimal`). One record per country and attribute;
  wheat US 2023 has 15.
- `country/all` is the largest answer and has no paging: corn 2023 is 1,875 records from
  125 countries, 275,759 bytes of JSON (`corn_all_2023`); wheat 2023 is 1,845 from 123.
- Release dates (`PSDData_GetDataReleaseInfo`; `models.DataReleaseInfo`): one record per
  country and market year, `commodityCode`, `countryCode`, `marketYear`, `releaseYear`,
  `releaseMonth`, all digit strings; a month, no day, no time, no zone. Wheat: 7,754
  records, 145 countries, market years 1960 to 2026, no world record, about 840 KB.
  `release_client` keeps the answer one hour (`RELEASE_DATES_CACHE`).
- A data record's `calendarYear`/`month` is the release that last revised it: for wheat
  2023 every one of the 123 countries matches its release record exactly, and the world
  records carry the latest of them (2026-10).
- `meta.published_at` of `get_data` and `get_world_data` comes from those release dates:
  the release month of the market year for the requested country, or the latest across
  countries for `country/all` and the world, as the first of that month 00:00 UTC (PSD
  gives the month only, so day and time are a convention). `None` when the list has no
  matching record or the answer is empty. `get_release_dates` leaves it `None`.

## Reference data

`scripts/refresh_reference.py` packages the five lists (`commodities`, `countries`,
`regions`, `unitsOfMeasure`, `commodityAttributes`) under `reference/` with provenance
in `reference/README.md`, and regenerates `enums.py`. Refresh policy:
`/refresh-reference-data` inside `/release-prep`, and whenever a validation failure
names a code the package lacks.

`enums.AttributeId` and `enums.UnitId` are `IntEnum`s, a deliberate departure from
conventions §3 ("upstream enums become `StrEnum`"): PSD's ids are integers in the lists
and in every data record, and fidelity to upstream wins. Where upstream gives two ids the
same name, both members carry the id (`TOTAL_DISAPPEARANCE_126`, `TOTAL_DISAPPEARANCE_173`).

## Read first, in this order

1. `docs/upstream/FETCHED.md` and the files it lists: what the upstream actually offers
2. The family conventions: `../sdk-core/docs/conventions.md` and `../sdk-core/docs/adr/`
   (also at https://github.com/xippios/sdk-core/tree/main/docs)
3. `../sdk-core/docs/definition-of-done.md`: what a PR must satisfy
4. The family file `../CLAUDE.md`

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
  tasks.py         task functions; __all__ is what the adapters register
  mcp.py           xippios-usda-psd-mcp entry point
  http.py          FastAPI router
  errors.py        UnknownCode: a code the packaged lists lack (InvalidRequestError)
  params.py        packaged lists (PACKAGED_LISTS, packaged_values()) and code checks
  enums.py         IntEnums AttributeId, UnitId from the packaged lists; never edited by hand
  reference/       packaged code lists (CSV/JSON) plus README with provenance
scripts/
  refresh_reference.py   fetches the packaged lists through api/ and regenerates enums.py
  check-siblings.sh      this wheel and xippios-usda-nass share xippios.usda (CI job siblings)
tests/
  conftest.py      enables xippios.core.testing.plugin; placeholder key for replay
  fixtures/        recorded responses, <endpoint>/<case>.json, never hand-written
  test_tasks.py    structural checks on every task plus per-task replay tests
  test_api.py      replay tests for the endpoint wrappers
  test_client.py   classify on recorded error bodies, quota snapshot and pause
  test_params.py   packaged lists, enums and the code checks
  test_adapters.py the adapters expose exactly tasks.__all__
  test_layout.py   namespace levels stay empty; py.typed ships
  test_live.py     @pytest.mark.live smoke tests, one per task
docs/upstream/     documentation snapshot and FETCHED.md
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep
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
   re-export it from `__init__.py`.
5. Docstring for agents: one sentence, then `Args:` with examples of valid values for
   every parameter. The MCP tool description and the OpenAPI summary come from it.
6. `/record-fixture` for at least one case, a replay test in `test_tasks.py` that also
   calls the tool end to end with `xippios.core.testing.mcp_call`, a live smoke test in
   `test_live.py`.
7. `CHANGELOG.md` under Unreleased, README status table, then the full check suite.

Reference lookups (commodities, countries, attributes) are tasks too, named
`list_<thing>`, so agents can form valid calls. A task-shaped function that returns a
subset of an upstream record builds its model with `UpstreamModel.project`; nothing is
renamed or computed, parsing a value (`parse_decimal`) is the only override. Upstream's
documented error shapes go into `ClientConfig.classify` in `_client.py`, once; wrappers
use `client.get_json` and never inspect status codes.

## How to record a fixture

Run `/record-fixture <endpoint> <case> <parameters>`. It performs one live request
through the real client with `xippios.core.testing.record_sync` and writes
`tests/fixtures/<endpoint>/<case>.json` with credentials scrubbed. Grep the file for
key patterns before committing. Fixtures are never typed in by hand.

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

## Workflow rules

- Branch from `main` as `feature/<topic>`, `fix/<topic>`, `chore/<topic>` or `docs/<topic>`.
  Never commit to `main`.
- Commit small, with Conventional Commits messages (`feat(tasks): add get_balance_sheet`).
- Open the PR with `gh pr create`; the body is the definition-of-done checklist from
  `.github/PULL_REQUEST_TEMPLATE.md`, ticked honestly, with assumptions listed.
- `ruff` leaves `docs/` alone; never reformat the upstream snapshot.
- Template updates: `uvx copier update` pulls the latest sdk-template tag into the
  infrastructure files (answers are in `.copier-answers.yml`; content files such as
  `tasks.py`, `api/`, `tests/` and `README.md` are never overwritten). Review the diff
  and open a `chore/template-update` PR.
- If a convention seems wrong, say so in the PR and follow it anyway; changing it is a
  PR against `sdk-core/docs/conventions.md` plus an ADR.

## Never

- Never hand-write a fixture, and never commit one without grepping for key patterns.
- Never read or print `.envrc`, `.env`, or any variable ending in `_API_KEY`.
- Never write a key into a file or a commit.
- Never put logic in `mcp.py` or `http.py`; never add a route or tool by hand.
- Never rename or re-map an upstream concept to another source's (ADR-0003).
- Never edit `docs/upstream/` by hand; `/refresh-upstream` fetches, a PR reviews.
- Never add `src/xippios/__init__.py`.
- Never tag, merge, release, force-push, or touch `gh secret`. Those are human actions.

## When something is unclear

Prefer the smallest change that satisfies the documents above, state the assumption in
the PR description, and stop rather than guess at upstream semantics or public API shape.
