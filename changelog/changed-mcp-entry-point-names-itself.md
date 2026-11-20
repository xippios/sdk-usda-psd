- `xippios-usda-psd-mcp` names itself in its usage line and its errors, an unknown option
  ending `xippios-usda-psd-mcp: error: unrecognized arguments: --<option>`, where they named
  the server, `xippios-usda-psd`. Its help says that `--allow-remote` changes nothing, since
  this read server is not held to loopback. (https://github.com/xippios/sdk-core/issues/167)
