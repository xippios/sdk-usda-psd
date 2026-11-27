- `get_release_dates` sets `meta.vintage` to the newest release of the whole list,
  `"YYYY-MM"` as the data tasks write it, also where `market_year`, `country_code` or `since`
  keep no record, where it left it empty, so a stored vintage passed as `since` polls for a
  newer release with one request. (https://github.com/xippios/sdk-usda-psd/issues/55)
