# Reference data for USDA FAS PSD Online

Code lists and calendars the upstream publishes (commodities, countries, report
schedules) ship here as CSV or JSON, versioned with the package, and load through
`xippios.core.reference`:

```python
from xippios.core import load_table

rows = load_table("xippios.usda.psd", "commodities.csv", Commodity)
```

Rules:

- Files come from the upstream through `scripts/refresh_reference.py`
  (`/refresh-reference-data`), never typed in by hand; the script also regenerates
  `enums.py`, one `StrEnum` per list, with `xippios.core.reference.render_str_enums`.
- Every file has a row below naming the endpoint or URL it came from and the date.
- Each packaged list gets a lookup task, `list_<thing>`, served as the MCP tool
  `usda_psd_list_<thing>` so agents can form valid calls; `/refresh-reference-data`
  adds the task where it is missing.

| File | Origin | Fetched |
| --- | --- | --- |
| (none yet) | | |
