"""Endpoint wrappers, layer 1: one async function per upstream operation (conventions §2).

``/add-endpoint`` adds them. A module and its function carry the snapshot's
``operationId`` in snake case, without the ``PSDData_`` prefix every PSD operation shares:
``PSDData_GetCommodities`` is ``get_commodities`` in ``get_commodities.py``. The verbatim
id stays in the first line of each wrapper's docstring and in the ``endpoint=`` it
passes, so ``meta.endpoint`` keeps upstream's exact name.
"""

from xippios.usda.psd.api.get_commodities import get_commodities
from xippios.usda.psd.api.get_commodity_attributes import get_commodity_attributes
from xippios.usda.psd.api.get_commodity_data_by_year import get_commodity_data_by_year
from xippios.usda.psd.api.get_countries import get_countries
from xippios.usda.psd.api.get_country_commodity_data_by_year import (
    get_country_commodity_data_by_year,
)
from xippios.usda.psd.api.get_data_release_info import get_data_release_info
from xippios.usda.psd.api.get_regions import get_regions
from xippios.usda.psd.api.get_units_of_measure import get_units_of_measure
from xippios.usda.psd.api.get_world_commodity_data_by_year import (
    get_world_commodity_data_by_year,
)

__all__ = [
    "get_commodities",
    "get_commodity_attributes",
    "get_commodity_data_by_year",
    "get_countries",
    "get_country_commodity_data_by_year",
    "get_data_release_info",
    "get_regions",
    "get_units_of_measure",
    "get_world_commodity_data_by_year",
]
