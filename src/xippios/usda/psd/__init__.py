"""Typed client, MCP tools and HTTP routes for USDA FAS PSD Online.

Distribution ``xippios-usda-psd``. Public API: ``__version__`` and the task
functions re-exported here. Endpoint wrappers under ``api/`` and the configured client
in ``_client`` are internal.
"""

from xippios.usda.psd._version import __version__

__all__ = ["__version__"]
