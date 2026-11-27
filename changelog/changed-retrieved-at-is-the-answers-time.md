- `meta.retrieved_at` of `get_data`, `get_world_data`, `get_release_dates` and
  `get_time_series` is the client's time of the answer, the time its entry was stored where
  core's cache answers it and the oldest of the market years that `get_time_series` puts
  together, where it read the time the answer's metadata was made.
  (https://github.com/xippios/sdk-core/issues/479)
