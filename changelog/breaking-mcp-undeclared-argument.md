- A tool refuses an argument that it does not declare before it runs, whatever its value:
  `usda_psd_get_data` called with `country` for `country_code` answers
  `error: InvalidRequestError: country: Not an argument of this tool` and names the
  arguments it takes, where the argument was dropped and the tool fetched every country.
  (https://github.com/xippios/sdk-core/issues/84)
