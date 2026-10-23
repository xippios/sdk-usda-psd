"""Structural checks every task must satisfy. Per-task tests with recorded fixtures go below."""

import inspect
import os

import httpx
import pytest

from xippios.usda.psd import __version__, tasks
from xippios.usda.psd._client import API_KEY_ENV, BASE_URL, auth

SHELL_KEY = os.environ.get(API_KEY_ENV)
"""The key the shell held when the tests were collected, before any fixture; never printed."""

TASKS = [getattr(tasks, name) for name in tasks.__all__]


def test_package_has_a_version() -> None:
    assert __version__


def test_replay_tests_send_the_placeholder_key(placeholder_api_key: str | None) -> None:
    """A request sent outside a live test carries the placeholder, never the shell's key.

    Every assertion is on a boolean, so a failure says where the key went, never the key.
    """
    assert placeholder_api_key is not None
    env_holds_placeholder = os.environ[API_KEY_ENV] == placeholder_api_key
    assert env_holds_placeholder, f"{API_KEY_ENV} does not hold the placeholder"
    sent = next(auth.sync_auth_flow(httpx.Request("GET", BASE_URL)))
    carried = sent.headers.get(auth.header, "")
    where = f"the {auth.header} header"
    sends_placeholder = carried == placeholder_api_key
    assert sends_placeholder, f"{where} does not carry the placeholder"
    if SHELL_KEY and placeholder_api_key != SHELL_KEY:
        outgoing = [str(sent.url), *sent.headers.values(), carried]
        leaked = any(SHELL_KEY in part for part in outgoing)
        assert not leaked, f"the key in {API_KEY_ENV} went out with the request"


@pytest.mark.parametrize("task", TASKS, ids=tasks.__all__)
def test_task_is_a_sync_facade_with_an_agent_docstring(task: object) -> None:
    assert callable(task)
    assert hasattr(task, "async_fn"), "write the async function and derive the sync one with sync()"
    doc = inspect.getdoc(task) or ""
    assert doc, "task functions need a docstring: agents read it"
    assert doc.splitlines()[0].endswith("."), "the first line is one sentence"
    if inspect.signature(task).parameters:
        assert "Args:" in doc, "explain every parameter under Args: with valid-value examples"
