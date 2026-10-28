"""Endpoint wrappers, layer 1: one async function per upstream operation (conventions §2).

``/add-endpoint`` adds them. Modules and functions carry the snapshot's ``operationId``
verbatim, e.g. ``PSDData_GetCommodities``.
"""

from xippios.usda.psd.api.PSDData_GetCommodities import PSDData_GetCommodities
from xippios.usda.psd.api.PSDData_GetCommodityAttributes import PSDData_GetCommodityAttributes
from xippios.usda.psd.api.PSDData_GetCommodityDataByYear import PSDData_GetCommodityDataByYear
from xippios.usda.psd.api.PSDData_GetCountries import PSDData_GetCountries
from xippios.usda.psd.api.PSDData_GetCountryCommodityDataByYear import (
    PSDData_GetCountryCommodityDataByYear,
)
from xippios.usda.psd.api.PSDData_GetDataReleaseInfo import PSDData_GetDataReleaseInfo
from xippios.usda.psd.api.PSDData_GetRegions import PSDData_GetRegions
from xippios.usda.psd.api.PSDData_GetUnitsOfMeasure import PSDData_GetUnitsOfMeasure
from xippios.usda.psd.api.PSDData_GetWorldCommodityDataByYear import (
    PSDData_GetWorldCommodityDataByYear,
)

__all__ = [
    "PSDData_GetCommodities",
    "PSDData_GetCommodityAttributes",
    "PSDData_GetCommodityDataByYear",
    "PSDData_GetCountries",
    "PSDData_GetCountryCommodityDataByYear",
    "PSDData_GetDataReleaseInfo",
    "PSDData_GetRegions",
    "PSDData_GetUnitsOfMeasure",
    "PSDData_GetWorldCommodityDataByYear",
]
