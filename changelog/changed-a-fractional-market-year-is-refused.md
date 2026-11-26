- A market year that is no whole number, a float such as `2023.5` or `2023.0` or a text, is
  refused with `InvalidRequestError` before any request, where it passed the check and
  reached the request's path, and the refusal names the argument it came in, `start_year` and
  `end_year` of `get_time_series` among them. (https://github.com/xippios/sdk-usda-psd/issues/27)
