- A market year that is no whole number, a float such as `2023.5` or `2023.0` or a text, is
  refused with `InvalidRequestError` before any request, and the refusal names the argument it
  came in, `start_year` and `end_year` of `get_time_series` among them. A float passed the
  range check and reached the request's path, and a text raised a bare `TypeError`.
  (https://github.com/xippios/sdk-usda-psd/issues/27)
