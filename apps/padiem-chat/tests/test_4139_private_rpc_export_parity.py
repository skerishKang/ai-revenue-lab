"""#4139: static source export parity for EXISTING canonical private RPCs.

This is NOT deployed-source attestation or proof of a callable Cloudflare
binding. There must be no side effects, accounts, RPCs or credential access.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps" / "padiem-chat" / "app"
CONTROL = ROOT / "packages" / "padiem-control-plane"


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _klass(path: Path, name: str) -> ast.ClassDef:
    classes = [n for n in _module(path).body
               if isinstance(n, ast.ClassDef) and n.name == name]
    assert len(classes) == 1, f"{path.name}: {name} source missing or ambiguous"
    return classes[0]


def _method(tree: ast.ClassDef, name: str) -> ast.AsyncFunctionDef:
    methods = [n for n in tree.body
               if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    assert len(methods) == 1, f"{tree.name}.{name}: private RPC missing or ambiguous"
    return methods[0]


def _binding_declarations() -> dict[str, tuple[str, ...]]:
    module = _module(APP / "canonical_connector_gateway_source_composition.py")
    values = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in (
            "_CONNECTOR_IDENTITY_RPC", "_CONNECTOR_BROKER_RPC",
        ):
            value = ast.literal_eval(node.value)
            assert type(value) is tuple and value
            assert all(type(v) is str and v.isidentifier() for v in value)
            assert len(value) == len(set(value))
            values[target.id] = value
    assert set(values) == {"_CONNECTOR_IDENTITY_RPC", "_CONNECTOR_BROKER_RPC"}
    return values


def _exact_private_delegate(node: ast.AsyncFunctionDef, name: str):
    """Require Default RPC to await the matching DO stub method, no detour."""
    assert [arg.arg for arg in node.args.args] == ["self", "payload"]
    assert not node.args.kwonlyargs and not node.args.defaults
    statements = [s for s in node.body if not (
        isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
        and type(s.value.value) is str
    )]
    assert len(statements) == 1
    ret = statements[0]
    assert isinstance(ret, ast.Return) and isinstance(ret.value, ast.Await)
    call = ret.value.value
    assert isinstance(call, ast.Call) and len(call.args) == 1 and not call.keywords
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "payload"
    target = call.func
    assert isinstance(target, ast.Attribute) and target.attr == name
    factory = target.value
    assert isinstance(factory, ast.Call) and not factory.args and not factory.keywords
    assert isinstance(factory.func, ast.Attribute) and factory.func.attr == "_stub"
    assert isinstance(factory.func.value, ast.Name) and factory.func.value.id == "self"


@pytest.mark.parametrize("axis,worker_file,do_class,mixin_file,mixin_class,methods", [
    (
        "identity", "identity_authority_worker.py", "CanonicalIdentityDurableObject",
        "canonical_connector_enrollment_consent_rpc.py",
        "CanonicalIdentityEnrollmentConsentRPC",
        "_CONNECTOR_IDENTITY_RPC",
    ),
    (
        "broker", "local_agent_broker_worker.py", "LocalAgentBrokerDurableObject",
        "canonical_broker_pairing_rpc.py", "CanonicalBrokerPairingRPC",
        "_CONNECTOR_BROKER_RPC",
    ),
])
def test_gateway_required_rpc_exported_by_single_canonical_worker(
    axis, worker_file, do_class, mixin_file, mixin_class, methods
):
    del axis
    contract = _binding_declarations()[methods]
    worker = CONTROL / worker_file
    entry = _klass(worker, "Default")
    durable = _klass(worker, do_class)
    mixin = _klass(CONTROL / mixin_file, mixin_class)
    assert any(isinstance(base, ast.Name) and base.id == mixin_class
               for base in durable.bases), "canonical DO inheritance drift"
    entry_names = [n.name for n in entry.body if isinstance(n, ast.AsyncFunctionDef)]
    for method in contract:
        assert entry_names.count(method) == 1
        _exact_private_delegate(_method(entry, method), method)
        # Broker revoke_binding exists directly on the DO, while its
        # enrollment RPCs live on the inherited existing pairing mixin.
        directly_owned = [n for n in durable.body
                          if isinstance(n, ast.AsyncFunctionDef) and n.name == method]
        if directly_owned:
            assert len(directly_owned) == 1
        else:
            _method(mixin, method)


def test_private_method_names_match_gateway_and_worker_binding_names():
    values = _binding_declarations()
    assert values["_CONNECTOR_IDENTITY_RPC"] == (
        "resolve_connector_enrollment_consent_for_device",
        "bind_connector_enrollment_challenge",
        "authorize_connector_enrollment_redeem",
    )
    assert values["_CONNECTOR_BROKER_RPC"] == (
        "gateway_bootstrap_rpc", "get_enrollment_binding",
        "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding",
    )
    config = _module(APP / "worker_config.py")
    constants = {}
    for node in config.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1             and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in (
                "IDENTITY_AUTHORITY_SERVICE_BINDING_NAME",
                "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME",
            ):
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    assert constants == {
        "IDENTITY_AUTHORITY_SERVICE_BINDING_NAME": "IDENTITY_AUTHORITY_SERVICE",
        "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME":
            "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE",
    }


def test_source_rpc_shape_does_not_enable_public_connector_mount():
    production = (ROOT / "apps/padiem-chat/worker.py").read_text("utf-8")
    factory = (APP / "app_factory.py").read_text("utf-8")
    assert "connector_gateway_worker_binding_composition" not in production
    assert "connector_gateway_worker_asgi_review" not in production
    assert "canonical_connector_gateway_source_composition" not in factory
    # A valid source method set can never claim deployed parity/activation.
    for file, symbol in (
        ("canonical_connector_gateway_source_composition.py",
         "CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED"),
        ("connector_gateway_worker_binding_composition.py",
         "WORKER_GATEWAY_PUBLIC_ENTRYPOINT_MOUNTED"),
        ("connector_gateway_worker_asgi_review.py",
         "WORKER_GATEWAY_ASGI_FETCH_PRODUCTION_WIRED"),
    ):
        src = _module(APP / file)
        flags = [n.value.value for n in src.body if isinstance(n, ast.Assign)
                 and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                 and n.targets[0].id == symbol and isinstance(n.value, ast.Constant)]
        assert flags == [False], f"{file}: production connector must remain OFF"
