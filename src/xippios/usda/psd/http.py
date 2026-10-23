"""FastAPI router for USDA FAS PSD Online.

``GET /usda-psd/<task>`` for every task. No logic lives here (ADR-0001). The
consumer mounts it; it is never served standalone.
"""

from xippios.core.http import router_from_tasks

from xippios.usda.psd import tasks
from xippios.usda.psd._client import SOURCE

router = router_from_tasks(SOURCE, [getattr(tasks, name) for name in tasks.__all__])

__all__ = ["router"]
