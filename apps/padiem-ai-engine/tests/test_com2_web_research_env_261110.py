"""#7306: the COM2 P01 host reads the same Engine web research names the Worker does.

The Engine worker (``worker.py``) reads ``PADIEM_ENGINE_WEB_PROVIDER`` and the
``PADIEM_ENGINE_*`` web credential/sort/timeout names through
``_engine_web_provider_for_env``. The CPython host passes its environment
through unchanged, but the shipped ``p01.env.example`` did not carry the names,
so the host operator had no reviewed place to set them and every Claw agent
turn that needed web research answered ``503 web_tools_off`` on this host only.

These tests pin the name contract and nothing else:

* the names the Worker reads are exactly the names the host example carries;
* an absent name stays absent (the reviewed fail-closed 503 is unchanged);
* a configured name reaches the host composition under the same name.
"""
from __future__ import annotations

import ast
from pathlib import Path

from app.local_runtime import _env_view

ENGINE_DIR = Path(__file__).resolve().parents[1]
WORKER_SOURCE = (ENGINE_DIR / "worker.py").read_text(encoding="utf-8")
ENV_EXAMPLE = (
    ENGINE_DIR.parents[1]
    / "deploy/host-com2/p01/p01.env.example"
).read_text(encoding="utf-8")


def _worker_env_constants() -> dict[str, str]:
    """String constants ``worker.py`` names its web research env with."""

    constants: dict[str, str] = {}
    for node in ast.parse(WORKER_SOURCE).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                constants[target.id] = node.value.value
    return constants


def _web_research_names() -> set[str]:
    """Every ``PADIEM_ENGINE_*`` web name the Worker's provider composer reads."""

    constants = _worker_env_constants()
    names: set[str] = set()
    for name in (
        "ENGINE_WEB_PROVIDER_ENV",
        "ENGINE_FIRECRAWL_API_KEY_ENV",
        "ENGINE_DAUM_REST_API_KEY_ENV",
        "ENGINE_TINYFISH_API_KEY_ENV",
        "ENGINE_DAUM_SEARCH_SORT_ENV",
        "ENGINE_WEB_TIMEOUT_SECONDS_ENV",
    ):
        assert name in constants, name
        names.add(constants[name])
    return names


def _example_names() -> set[str]:
    names: set[str] = set()
    for line in ENV_EXAMPLE.splitlines():
        if not line or line.startswith("#"):
            continue
        name, sep, _value = line.partition("=")
        if sep:
            names.add(name)
    return names


def test_the_worker_and_the_host_example_carry_the_same_web_research_names():
    required = _web_research_names()
    assert required == {
        "PADIEM_ENGINE_WEB_PROVIDER",
        "PADIEM_ENGINE_FIRECRAWL_API_KEY",
        "PADIEM_ENGINE_DAUM_REST_API_KEY",
        "PADIEM_ENGINE_TINYFISH_API_KEY",
        "PADIEM_ENGINE_DAUM_SEARCH_SORT",
        "PADIEM_ENGINE_WEB_TIMEOUT_SECONDS",
    }
    missing = required - _example_names()
    assert not missing, f"p01.env.example is missing {sorted(missing)}"


def test_an_absent_web_research_name_keeps_the_provider_off():
    env = _env_view({})
    assert env.PADIEM_ENGINE_WEB_PROVIDER is None
    assert env.PADIEM_ENGINE_DAUM_REST_API_KEY is None
    assert env.PADIEM_ENGINE_TINYFISH_API_KEY is None


def test_a_configured_web_research_name_reaches_the_host_composition():
    values = {
        "PADIEM_ENGINE_WEB_PROVIDER": "tinyfish_daum",
        "PADIEM_ENGINE_DAUM_REST_API_KEY": "synthetic-daum-key",
        "PADIEM_ENGINE_TINYFISH_API_KEY": "synthetic-tinyfish-key",
        "PADIEM_ENGINE_DAUM_SEARCH_SORT": "accuracy",
        "PADIEM_ENGINE_WEB_TIMEOUT_SECONDS": "30",
    }
    env = _env_view(values)
    for name, expected in values.items():
        assert getattr(env, name) == expected, name
