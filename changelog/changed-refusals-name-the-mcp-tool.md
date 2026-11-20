- A refusal that names another task names its MCP tool too, so an agent calls the tool it
  is told of: the country code `00` points to `get_world_data` (over MCP, the tool
  `usda_psd_get_world_data`), as does the region `R00`, an attribute id the packaged list
  lacks to `list_commodity_attributes` (`usda_psd_list_commodity_attributes`), and a region
  no country carries to `list_regions` and `list_countries` (`usda_psd_list_regions`,
  `usda_psd_list_countries`). (https://github.com/xippios/sdk-core/issues/111)
