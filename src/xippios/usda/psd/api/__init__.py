"""Endpoint wrappers for USDA FAS PSD Online.

Layer 1 of ADR-0001: one module per upstream operation, named after it. A wrapper
takes the parameters as upstream names them (snake_cased), calls
``xippios.usda.psd._client.client`` and returns models from ``models.py`` that
mirror the payload. No composition and no defaults beyond upstream's own. The reference
is the snapshot in ``docs/upstream/``; modules and functions carry the snapshot's
``operationId`` verbatim, e.g. ``PSDData_GetCommodities``.
"""

from xippios.usda.psd.api.PSDData_GetCommodities import PSDData_GetCommodities
from xippios.usda.psd.api.PSDData_GetCommodityAttributes import PSDData_GetCommodityAttributes
from xippios.usda.psd.api.PSDData_GetCountries import PSDData_GetCountries
from xippios.usda.psd.api.PSDData_GetRegions import PSDData_GetRegions
from xippios.usda.psd.api.PSDData_GetUnitsOfMeasure import PSDData_GetUnitsOfMeasure

__all__ = [
    "PSDData_GetCommodities",
    "PSDData_GetCommodityAttributes",
    "PSDData_GetCountries",
    "PSDData_GetRegions",
    "PSDData_GetUnitsOfMeasure",
]
