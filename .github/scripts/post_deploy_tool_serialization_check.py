"""Zero-cost post-deploy check: the connector tool payload must serialize.

#7088 후속 (measured 2026-11-08): a Core ``ToolSpec`` schema travels through
``ToolDefinition`` as recursively frozen ``MappingProxyType`` values.
``to_provider_schema`` shallow-converts only the ``properties`` mapping, so a
declared tool whose schema carries nested structures reached ``json.dumps``
inside the B14 stream client and died there as ``TypeError`` — masked by the
Core runtime as ``execution_failed`` before a single byte left for the model.

This check runs after the chat deploy with the chat service's own venv (the
only interpreter that can import the staged app modules), builds the real
connector declarations and serializes the exact provider payload the next
connector-intent turn will send. It is read-only, costs no model call and
needs no credentials, so it runs on every deploy regardless of the QA login.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

FAIL_IMPORT = "tool_declarations_import_failed"
FAIL_SERIALIZE = "tool_payload_serialization_failed"
FAIL_NO_TOOLS = "no_connector_tools_declared"


def verdict(staged_app: Path) -> tuple[str, str]:
    """Return ``(verdict, bounded code)`` for one staged chat app tree."""
    sys.path.insert(0, str(staged_app))
    core_src = staged_app.parents[2] / "packages" / "padiem-ai-core"
    if core_src.is_dir():
        sys.path.insert(0, str(core_src))
    # Every staged tree is imported fresh: a previous check in the same
    # process must not leak its cached app module into this verdict.
    sys.modules.pop("app.chat_connector_tools", None)
    sys.modules.pop("app", None)
    try:
        tools = importlib.import_module("app.chat_connector_tools").CONNECTOR_TOOL_DECLARATIONS
    except Exception:
        return "FAIL", FAIL_IMPORT
    finally:
        sys.path.pop(0)
        sys.modules.pop("app.chat_connector_tools", None)
        sys.modules.pop("app", None)
    if not tools:
        return "FAIL", FAIL_NO_TOOLS
    try:
        payload = {"tools": [tool.to_provider_schema() for tool in tools],
                   "tool_choice": "auto"}
        json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return "FAIL", FAIL_SERIALIZE
    return "PASS", "none"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged-app", required=True, type=Path,
                        help="staged apps/padiem-chat directory (the tree the service runs)")
    verdict_, code = verdict(parser.parse_args().staged_app)
    print(f"TOOLS_SERIALIZATION={verdict_}" + (f" code={code}" if code != "none" else ""))
    return 0 if verdict_ == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
