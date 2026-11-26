- The arguments that identify a record stay positional in the order of upstream's path, and
  every optional filter and every argument of the package's own is keyword-only:
  `get_data(commodity_code, market_year, *, country_code=None)`, `get_time_series(commodity_code,
  country_code, *, start_year, end_year, attribute_id=None)`, `get_release_dates(commodity_code,
  *, market_year=None, country_code=None, since=None)`, `list_countries(*, region_code=None,
  search=None)`, `list_commodities(*, search=None)` and `list_commodity_attributes(*,
  search=None)`. A call that passes one of them by position fails with `TypeError`, and over
  MCP and HTTP nothing changes. (https://github.com/xippios/sdk-usda-esr/issues/60)
