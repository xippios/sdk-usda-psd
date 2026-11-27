- `list_countries` names the region asked for in `meta.names` on every answer, one that keeps
  no country too, by PSD's regions list, and `R15`, which that list lacks, by its code alone.
  A refusal of a region code shows `R15` among the closest codes by its code, since the
  package builds no name of its own. (sdk-core ADR-0060, sdk-core ADR-0067,
  https://github.com/xippios/sdk-usda-psd/issues/65)
