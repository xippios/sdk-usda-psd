# What PSD does but never documents

Notes, written by hand, on what USDA FAS PSD Online's API does that no page of this snapshot
states (sdk-core's conventions §3, sdk-core ADR-0028). The two Swagger documents under
`openapi/` are the reference for names and parameters: they type `commodityCode` and
`countryCode` as strings and `marketYear` as `int32`, describe every operation's answer as
`type: object` and define no schema beside it. The answers' shapes, PSD's empty answers and
the gateway's refusals below come from the wire, and `models.py`, `_client.classify` and
`tests/fixtures/` follow it. `scripts/refresh_upstream.py` neither writes nor checks this
file, and `FETCHED.md` lists it in a row of its own.

Each note ends with its probe: the date, the operation by the `operationId` the snapshot
gives it, and the sample, a fixture named by its path under `tests/fixtures/`, whose
`recorded_at` gives the time of the request. The answers recorded whole on 2026-10-23 that
the fixtures of 2026-10-28 keep cut are in commit `07b88ad` of `main`, and a note read
across them ends with `Observed:` and that commit in place of a fixture. The notes moved
here on 2026-11-26 from `CLAUDE.md`; no request was sent to write this file.

## The answers' shapes

### The five lists

Unit descriptions are padded with spaces to 20 characters (`"(1000 MT)           "`);
attribute names are not unique (`Total Disappearance` is 126 and 173, `Fresh Dom.
Consumption` 133 and 135); four countries sit in region `R15`, which `PSDData_GetRegions`
does not list. The record shapes are in `models.py`, each naming its fixture.

Probe: 2026-10-23, `PSDData_GetCommodities`, `PSDData_GetCountries`, `PSDData_GetRegions`,
`PSDData_GetUnitsOfMeasure` and `PSDData_GetCommodityAttributes`; samples
`tests/fixtures/get_commodities/all.json`, `tests/fixtures/get_countries/all.json`,
`tests/fixtures/get_regions/all.json`, `tests/fixtures/get_units_of_measure/all.json` and
`tests/fixtures/get_commodity_attributes/all.json`.

### The data records

The three data operations answer the same record, one per country and attribute (wheat in
the United States, 2023: 15): `commodityCode`, `countryCode` (`"00"` in world records),
`marketYear`, `calendarYear` and `month` as digit strings (`"2023"`, `"2026"`, `"07"`),
`attributeId` and `unitId` as integers and `value` as a JSON number with four fractional
digits (`222218.0000`). Every recorded id is in the packaged lists.

Probe: 2026-10-23, `PSDData_GetCountryCommodityDataByYear` and
`PSDData_GetWorldCommodityDataByYear`; samples
`tests/fixtures/get_country_commodity_data_by_year/wheat_us_2023.json` and
`tests/fixtures/get_world_commodity_data_by_year/wheat_world_2023.json`.

### Every country at once

`country/all` is the largest answer and has no paging: corn 2023 was 1,875 records and
275,759 bytes of JSON, wheat 2023 1,845 records and 271,470 bytes, both ordered by country
code, and on 2026-10-23 the whole answers held 125 and 123 countries. The fixtures are cut
at 200,000 bytes and keep the countries from AF to RH (corn) and to RS (wheat), the whole
sizes in their `original_count` and `original_bytes`.

Probe: 2026-10-28, `PSDData_GetCommodityDataByYear`; samples
`tests/fixtures/get_commodity_data_by_year/corn_all_2023.json` and
`tests/fixtures/get_commodity_data_by_year/wheat_all_2023.json`, recorded cut.

### The release list

One record per country and market year, `commodityCode`, `countryCode`, `marketYear`,
`releaseYear` and `releaseMonth`, all digit strings: a month, no day, no time, no zone.
Wheat's list was 7,754 records and 837,433 bytes, ordered by market year, oldest first,
within a year by country code on 2026-10-28 and in another order on 2026-10-23, so the cut
fixture keeps market years 1960 to 1978, whose newest release is 2024-02. The whole list of
2026-10-23 held 145 countries, market years 1960 to 2026 and no world record.

Probe: 2026-10-28, `PSDData_GetDataReleaseInfo`; sample
`tests/fixtures/get_data_release_info/wheat.json`, recorded cut.

### A data record names the release that last revised it

A data record's `calendarYear` and `month` are the release that last revised it: for wheat
2023 every one of the 123 countries matched its record of the release list exactly, and the
world records carried the latest of them, 2026-10. In every case recorded with its whole
release list (wheat 2023: the United States, every country and the world) the latest
`calendarYear`-`month` of an answer equals the release list's record for the same commodity,
market year and country, or the latest across countries, and the corn and soybeans
recordings are consistent in themselves; the cut release list ends at market year 1978, so
no replay test checks it on 2023.

Observed: 2026-10-23, `PSDData_GetCountryCommodityDataByYear`,
`PSDData_GetCommodityDataByYear`, `PSDData_GetWorldCommodityDataByYear` and
`PSDData_GetDataReleaseInfo`, in the whole answers of commit `07b88ad`.

## Empty answers and refusals

### Unknown codes and codes without data answer the empty list

An unknown commodity code (`commodity/9999999/country/US/year/2023`) and an unknown country
code (`commodity/0410000/country/XX/year/2023`) answer HTTP 200 with `[]`, and so do valid
codes without data: wheat for Bermuda in 2023 (`commodity/0410000/country/BD/year/2023`;
PSD's `BM` is Burma, which has wheat data).

Probe: 2026-10-23, `PSDData_GetCountryCommodityDataByYear`; samples
`tests/fixtures/get_country_commodity_data_by_year/unknown_commodity.json`,
`tests/fixtures/get_country_commodity_data_by_year/unknown_country.json` and
`tests/fixtures/get_country_commodity_data_by_year/no_data_valid_codes.json`.

### A market year without data answers an empty 404

Market year 1900 answers HTTP 404 with an empty `text/plain` body on every data form: one
country, every country and the world. A market year PSD has not released is expected to
answer alike; it was not recorded.

Probe: 2026-10-23, `PSDData_GetCountryCommodityDataByYear`,
`PSDData_GetCommodityDataByYear` and `PSDData_GetWorldCommodityDataByYear`; samples
`tests/fixtures/get_country_commodity_data_by_year/unknown_year.json`,
`tests/fixtures/get_commodity_data_by_year/year_1900.json` and
`tests/fixtures/get_world_commodity_data_by_year/year_1900.json`.

### The gateway refuses an invalid key

An invalid key answers HTTP 403 `{"error": {"code": "API_KEY_INVALID", "message": "An invalid
api_key was supplied. Get one at https://api.fas.usda.gov:443"}}`, with no quota headers.

Probe: 2026-10-23, `PSDData_GetCommodities`; sample
`tests/fixtures/get_commodities/invalid_key.json`.

### The gateway's hourly quota

Every keyed answer carries `x-ratelimit-limit: 1000` and `x-ratelimit-remaining`, and `via`
names api.data.gov's API Umbrella. The quota was spent on purpose on 2026-10-23, 987 calls
at the client's pace, and a fresh process then recorded HTTP 429 `{"error": {"code":
"OVER_RATE_LIMIT", "message": "You have exceeded your rate limit. Try again later or contact
us for assistance: https://api.fas.usda.gov:443"}}` with `Retry-After: 3151`,
`x-ratelimit-limit: 1000` and `x-ratelimit-remaining: 0`. api.data.gov's developer manual
says "The block will automatically be lifted by waiting an hour", the wait for the 200 that
left `remaining` at 0, which carries no `Retry-After`.

Probe: 2026-10-23, `PSDData_GetCommodities`; sample
`tests/fixtures/get_commodities/over_rate_limit.json`.
