- `get_time_series` spans at most 24 market years over MCP, where it spanned 100, and the
  option `--series-years` of the MCP server sets the ceiling from 1 to 100; in Python and over
  HTTP it stays 100. A longer range is refused before the first request in xippios-core's
  wording, which names the range, the ceiling and the option and says that nothing was sent.
  (sdk-core ADR-0054, https://github.com/xippios/sdk-usda-psd/issues/55)
