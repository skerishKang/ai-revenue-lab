"""#4139: test-only 3-Worker fixtures must match reviewed canonical RPC ports.

Fail closed on source drift; this NEVER imports or invokes production DOs.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


CANARY = Path(__file__).resolve().parents[1]
ROOT = CANARY.parents[1]
CHAT = ROOT / "apps" / "padiem-chat" / "app"
CONTROL = ROOT / "packages" / "padiem-control-plane"


def _file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class(path: Path, klass: str) -> ast.ClassDef:
    entries = [x for x in _file(path).body
               if isinstance(x, ast.ClassDef) and x.name == klass]
    if len(entries) != 1:
        raise AssertionError(f"missing or duplicated WorkerEntrypoint in {path.name}")
    return entries[0]


def _async_exports(entry: ast.ClassDef) -> set[str]:
    names = [n.name for n in entry.body if isinstance(n, ast.AsyncFunctionDef)]
    if len(names) != len(set(names)):
        raise AssertionError("RPC exports cannot be duplicated")
    return set(names) - {"fetch"}


def _gateway_required() -> dict[str, tuple[str, ...]]:
    parsed = _file(CHAT / "canonical_connector_gateway_source_composition.py")
    found = {}
    for node in parsed.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in (
                "_CONNECTOR_IDENTITY_RPC", "_CONNECTOR_BROKER_RPC"):
            found[target.id] = ast.literal_eval(node.value)
    if set(found) != {"_CONNECTOR_IDENTITY_RPC", "_CONNECTOR_BROKER_RPC"}:
        raise AssertionError("canonical private RPC exports missing")
    return found


def _mock_denial_only(entry: ast.ClassDef, required: tuple[str, ...]) -> None:
    for method in required:
        functions = [n for n in entry.body
                     if isinstance(n, ast.AsyncFunctionDef) and n.name == method]
        if len(functions) != 1:
            raise AssertionError(f"missing mock {method}")
        fn = functions[0]
        if [a.arg for a in fn.args.args] != ["self", "payload"]:
            raise AssertionError(f"RPC argument shape drift {method}")
        if len(fn.body) != 1 or not isinstance(fn.body[0], ast.Return):
            raise AssertionError("mock RPC may do nothing except deny")
        value = fn.body[0].value
        if not isinstance(value, ast.Name) or value.id != "_DENIAL":
            raise AssertionError("mock RPC must return fixed _DENIAL")


class SourceMockParity(unittest.TestCase):
    def test_identity_and_broker_mocks_match_existing_canonical_rpc_exports(self):
        required = _gateway_required()
        examples = (
            ("_CONNECTOR_IDENTITY_RPC", "identity_authority_worker.py",
             "rpc_identity_fixture.py"),
            ("_CONNECTOR_BROKER_RPC", "local_agent_broker_worker.py",
             "rpc_broker_fixture.py"),
        )
        for key, worker, mock in examples:
            methods = required[key]
            actual_worker = _class(CONTROL / worker, "Default")
            test_worker = _class(CANARY / mock, "Default")
            self.assertTrue(set(methods).issubset(_async_exports(actual_worker)))
            self.assertEqual(_async_exports(test_worker), set(methods))
            _mock_denial_only(test_worker, methods)

    def test_canary_gateway_source_exact_port_list(self):
        required = _gateway_required()
        fixture = _file(CANARY / "rpc_gateway_fixture.py")
        values = {}
        for x in fixture.body:
            if (isinstance(x, ast.Assign) and len(x.targets) == 1
                    and isinstance(x.targets[0], ast.Name)
                    and x.targets[0].id in ("_IDENTITY", "_BROKER")):
                values[x.targets[0].id] = ast.literal_eval(x.value)
        self.assertEqual(values, {
            "_IDENTITY": required["_CONNECTOR_IDENTITY_RPC"],
            "_BROKER": required["_CONNECTOR_BROKER_RPC"],
        })

    def test_rpc_fixture_remains_unbound_and_local_only(self):
        for name in ("rpc_gateway_fixture.py", "rpc_identity_fixture.py",
                     "rpc_broker_fixture.py"):
            file = CANARY / name
            data = file.read_text(encoding="utf-8")
            for marker in ("CLOUDFLARE_API_TOKEN", "os.environ", "D1",
                           "LOCAL_AGENT_BROKER_PEPPER", "DurableObject"):
                self.assertNotIn(marker, data, f"{name} should never own authority")
        script = (CANARY / "ci_private_rpc_local_probe.sh").read_text("utf-8")
        self.assertIn("padiem-local-4139-test-only-", script)
        self.assertIn("uv run pywrangler dev", script)
        self.assertNotIn("--remote", script)
        self.assertNotIn("pywrangler deploy", script)


if __name__ == "__main__":
    unittest.main()
