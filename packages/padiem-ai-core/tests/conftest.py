import asyncio
import inspect
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Allow async test functions to execute in vanilla pytest without pytest-asyncio."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        kwargs = {arg: pyfuncitem.funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames if arg in pyfuncitem.funcargs}
        asyncio.run(pyfuncitem.obj(**kwargs))
        return True
    return None
