- The MCP tools `usda_psd_get_data` and `usda_psd_get_release_dates` take `offset`, the rows
  already shown: a cut answer's note ends with `continue with offset=<n>`, and each
  continuation runs the task again, which core's response cache answers.
  (sdk-core ADR-0047, https://github.com/xippios/sdk-usda-psd/issues/31)
