import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

# #3658: prove the package under test came from THIS checkout before collecting anything.
#
# A user-level interpreter is shared by every concurrent worktree, and an editable install records
# the absolute path of the worktree that installed it. So `python -m pytest
# packages/padiem-ai-core/tests/...` from the repository root -- with no PYTHONPATH pin -- imports
# `padiem_ai_core` from some other lane's tree and can pass while testing code nobody in this
# checkout reviewed. The check itself lives in scripts/verify_import_origin.py so every lane can use
# the same rule.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_GUARD_PATH = _REPO_ROOT / "scripts" / "verify_import_origin.py"


def _origin_guard():
    if "_lovebud_import_origin_guard" in sys.modules:
        return sys.modules["_lovebud_import_origin_guard"]
    if not _GUARD_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("_lovebud_import_origin_guard", _GUARD_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pytest_configure(config) -> None:
    guard = _origin_guard()
    if guard is None:  # packaged/sdist run without the tooling tree: nothing to prove, do not block
        return

    verdict = guard.check_origins(("padiem_ai_core",), _REPO_ROOT)
    origin = verdict.origins[0]

    if origin.absent:
        return  # not importable at all is a different failure; let the normal ImportError surface it

    if not origin.inside_repository:
        raise pytest.UsageError(
            "padiem_ai_core resolves outside this checkout, so a passing run here would prove "
            f"nothing.\n  EXPECTED_CHECKOUT_ROOT={_REPO_ROOT}\n  ACTUAL_ORIGIN={origin.origin}\n"
            "Run the suite from the package root, or pin this tree explicitly, e.g.:\n"
            f"  cd {_REPO_ROOT / 'packages' / 'padiem-ai-core'} && python -m pytest tests\n"
            f"  PYTHONPATH={Path('packages') / 'padiem-ai-core'} python -m pytest "
            f"{Path('packages') / 'padiem-ai-core' / 'tests'}"
        )


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Allow async test functions to execute in vanilla pytest without pytest-asyncio."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        kwargs = {arg: pyfuncitem.funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames if arg in pyfuncitem.funcargs}
        asyncio.run(pyfuncitem.obj(**kwargs))
        return True
    return None
