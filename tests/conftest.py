import pytest

pytest_plugins = ["xippios.core.testing.plugin"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
