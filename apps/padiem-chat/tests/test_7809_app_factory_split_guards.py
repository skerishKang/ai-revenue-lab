"""#7809 app_factory PR0: structural guards before ownership moves.

These tests use Python object identity, compiled global reads, AST structure,
real route order and middleware wiring. No new raw source-substring contracts.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from starlette.routing import Mount, Route

from _support import app_factory_modules as fm


def test_registry_exactly_matches_staged_app_factory_modules():
    files = {p.stem for p in fm.APP_DIR.glob("app_factory*.py")}
    assert set(fm.FACTORY_MODULES) == files, "register each new app_factory_* owner in FACTORY_MODULES"
    assert len(fm.FACTORY_MODULES) == len(files)


def test_planned_areas_are_unique_and_pr0_has_no_moved_code():
    assert len(fm.SPLIT_PLAN) == len(set(fm.SPLIT_PLAN))
    assert set(fm.FACTORY_MODULES) <= (set(fm.SPLIT_PLAN) | {fm.ENTRY_MODULE})
    assert fm.FACTORY_MODULES[0] == fm.ENTRY_MODULE
    assert fm.SPLIT_PLAN[0] == "app_factory_health_static"
    assert fm.MODULE_LEVELS[fm.ENTRY_MODULE] > max(
        fm.MODULE_LEVELS[name] for name in fm.SPLIT_PLAN
    )


def test_each_top_level_definition_has_only_one_owner():
    owners = {}
    duplicates = []
    for mod in fm.modules():
        for name in fm.defined_names(mod):
            if name in owners:
                duplicates.append((name, owners[name], fm.short_name(mod)))
            owners[name] = fm.short_name(mod)
    assert not duplicates, duplicates


def test_facade_reexports_every_public_legacy_name_with_exact_identity():
    facade = fm.modules([fm.ENTRY_MODULE])[0]
    assert len(fm.ENTRY_EXPORTS) == len(set(fm.ENTRY_EXPORTS))
    for name in fm.ENTRY_EXPORTS:
        owner = fm.definition_owner(name)
        assert hasattr(facade, name), f"facade lacks {name}"
        assert getattr(facade, name) is getattr(owner, name), name


@pytest.mark.parametrize("module_name", fm.FACTORY_MODULES)
def test_area_module_imports_only_lower_level_owners(module_name):
    level = fm.MODULE_LEVELS[module_name]
    mod = fm.modules([module_name])[0]
    bad = []
    for target in fm.imported_factory_modules(mod):
        if target not in fm.FACTORY_MODULES:
            bad.append((target, "unregistered"))
        elif fm.MODULE_LEVELS[target] >= level:
            bad.append((target, "same or higher dependency"))
    assert bad == [], bad


def test_factory_create_app_signature_is_original_91_optional_parameters():
    factory = fm.modules()[0]
    params = list(inspect.signature(factory.create_app).parameters.values())
    assert len(params) == 91
    assert all(param.default is not inspect.Parameter.empty for param in params)
    assert params[0].name == "settings"
    assert params[-1].name == "news_store"


def test_default_route_order_starts_with_health_and_ends_with_static_catch_all():
    factory = fm.modules()[0]
    routes = factory.build_routes(None, None, None, None)
    assert len(routes) > 300
    assert isinstance(routes[0], Route)
    assert routes[0].path == fm.PUBLIC_ROUTE_HEAD[0]
    assert routes[0].endpoint is factory.health
    assert isinstance(routes[-1], Mount)
    # Starlette normalizes Mount('/') to an empty .path in some versions.
    assert routes[-1].path.rstrip("/") == fm.STATIC_CATCH_ALL.rstrip("/")
    assert all(r is not routes[-1] for r in routes[:-1])


def test_route_registrars_are_invoked_in_exact_baseline_order(monkeypatch):
    factory = fm.modules()[0]
    seen = []
    assert len(fm.REGISTRATION_ORDER) == 26
    for name in fm.REGISTRATION_ORDER:
        def record(*_args, _name=name, **_kwargs):
            seen.append(_name)
        fm.patch_bound(monkeypatch, name, record)
    factory.build_routes(None, None, None, None)
    assert seen == list(fm.REGISTRATION_ORDER)


@pytest.mark.parametrize(
    "shared,shadow,expected",
    (
        (False, False, ("SessionRevocationGuardMiddleware",
                         "SameOriginGuardMiddleware", "RequestTelemetryMiddleware")),
        (True, True, ("SessionRevocationGuardMiddleware", "SharedSessionMiddleware",
                      "ConnectorAccountShadowContextMiddleware",
                      "SameOriginGuardMiddleware", "RequestTelemetryMiddleware")),
    ),
)
def test_middleware_registration_and_conditions_preserve_security_order(
    shared, shadow, expected,
):
    factory = fm.modules()[0]
    observed = []

    class Receiver:
        def add_middleware(self, middleware_type, **_kwargs):
            observed.append(middleware_type.__name__)

    resolved = SimpleNamespace(
        connector_account_shadow_enabled=shadow,
        connector_account_key_enabled=False,
        pc_scope_tenant_only_enabled=False,
    )
    factory.install_middleware(Receiver(), resolved, None, None, object() if shared else None)
    assert tuple(observed) == expected


def test_patch_guard_rejects_reexport_only_and_reaches_real_execution(monkeypatch):
    leaf = ModuleType("_app_factory_pr0_leaf")
    entry = ModuleType("_app_factory_pr0_entry")
    exec(
        "def dependency():\n    return 'original'\n\n"
        "def caller():\n    return dependency()\n",
        leaf.__dict__,
    )
    entry.dependency = leaf.dependency
    entry.caller = leaf.caller

    with pytest.raises(AssertionError, match="vacuous patch"):
        fm.patch_targets("dependency", [entry])
    assert fm.patch_targets("dependency", [entry, leaf]) == (leaf,)
    assert entry.caller() == "original"
    fm.patch_bound(monkeypatch, "dependency", lambda: "replaced", [entry, leaf])
    assert entry.caller() == "replaced"
    assert entry.dependency() == "original"


def test_patch_guard_never_confuses_attribute_access_with_global_read():
    module = ModuleType("_app_factory_pr0_attribute_only")
    exec(
        "class Holder:\n    dependency = 'attr'\n"
        "holder = Holder()\n"
        "def caller():\n    return holder.dependency\n"
        "dependency = 'unused'\n",
        module.__dict__,
    )
    assert "dependency" not in fm.runtime_global_reads(module)
    with pytest.raises(AssertionError, match="vacuous patch"):
        fm.patch_targets("dependency", [module])


def test_function_transfer_helper_provides_exact_block_and_parseable_ast():
    owner = fm.definition_owner("councillor_redirect")
    text, original = fm.function_block(owner, "councillor_redirect")
    parsed = ast.parse(text)
    assert len(parsed.body) == 1
    assert ast.dump(parsed.body[0], include_attributes=False) == ast.dump(
        original, include_attributes=False
    )
    assert isinstance(original, ast.AsyncFunctionDef)


def test_unknown_or_duplicate_definition_owner_is_rejected():
    factory = fm.modules()[0]
    with pytest.raises(AssertionError, match="expected one"):
        fm.definition_owner("_this_definition_does_not_exist_", [factory])
    with pytest.raises(AssertionError, match="expected one"):
        fm.definition_owner("create_app", [factory, factory])
