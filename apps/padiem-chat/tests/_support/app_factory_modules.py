"""#7809 app_factory PR0: area registry and ownership-safe structural helpers.

No application definition moves in PR0. A later single-area PR adds exactly one
app_factory_* module to FACTORY_MODULES, reexports moved names from app_factory,
and verifies its own same-source/AST transfer against the parent main commit.

The registry follows tests/_support/claw_general_modules.py, but uses *AST
structure* rather than testing arbitrary source-string fragments.
"""
from __future__ import annotations

import ast
import dis
import importlib
from pathlib import Path
from types import ModuleType
from typing import Iterable

APP_DIR = Path(__file__).resolve().parents[2] / "app"
ENTRY_MODULE = "app_factory"

# One new owner module at a time. PR0 deliberately registers only the facade.
FACTORY_MODULES: tuple[str, ...] = (
    ENTRY_MODULE,
    "app_factory_health_static",
    "app_factory_routes_ops_admin",
)

# A single owner/area per future PR, not a requirement to reach 300 lines.
# State-wrapper internal slices are separate later phases and require explicit
# state-injection parity evidence before extracting their inner statements.
SPLIT_PLAN: tuple[str, ...] = (
    "app_factory_health_static",
    "app_factory_routes_ops_admin",
    "app_factory_routes_auth",
    "app_factory_routes_connectors",
    "app_factory_routes_projects",
    "app_factory_routes_chat",
    "app_factory_routes_web_xlsx",
    "app_factory_routes_b66",
    "app_factory_routes_claw",
    "app_factory_routes_calendar",
    "app_factory_routes_pc",
    "app_factory_routes_static",
    "app_factory_routes_enrollment",
    "app_factory_routes_mesh",
    "app_factory_routes_shared",
    "app_factory_route_catalog",
    "app_factory_middleware",
    "app_factory_state_core",
    "app_factory_state_platform",
    "app_factory_state_auth",
    "app_factory_state_documents",
    "app_factory_state_web_xlsx",
    "app_factory_state_claw_drive",
    "app_factory_state_claw_runtime",
    "app_factory_state_pc_mesh",
    "app_factory_state_telegram",
    "app_factory_state_memory",
    "app_factory_state_b66",
    "app_factory_state_push",
    "app_factory_state_calendar",
)

# A leaf may import other non-factory modules; a split component must never
# import the higher-level facade. Route catalogue and composition come later.
MODULE_LEVELS: dict[str, int] = {
    **{name: 0 for name in SPLIT_PLAN if name.startswith("app_factory_state_") or name == "app_factory_health_static"},
    **{name: 1 for name in SPLIT_PLAN if name.startswith("app_factory_routes_")},
    "app_factory_route_catalog": 2,
    "app_factory_middleware": 2,
    ENTRY_MODULE: 3,
}

# These pre-existing values/definitions must remain the *same objects* at
# app.app_factory on every step, not wrappers/copies with similar behavior.
ENTRY_EXPORTS: tuple[str, ...] = (
    "STATIC_DIR", "COUNCILLOR_REDIRECT_PATH",
    "councillor_redirect", "health", "_health_detail_allowed",
    "_health_detail", "CachedStaticFiles",
    "register_util_routes", "register_opinion_news_routes",
    "register_ops_member_routes", "register_ops_round_score_routes",
    "register_ops_alert_routes", "register_ops_pc_self_heal_routes",
    "register_ops_news_routes", "register_pc_helper_version_routes",
    "register_admin_feedback_routes", "register_site_feedback_routes",
    "register_admin_routes", "register_auth_voice_routes",
    "register_auth_login_routes", "register_connector_routes",
    "register_project_document_routes", "register_chat_routes",
    "register_b66_routes", "register_web_xlsx_routes",
    "register_claw_routes", "register_calendar_routes",
    "register_pc_routes", "register_static_routes",
    "register_connector_enrollment_routes", "register_oracle_mesh_routes",
    "register_shared_auth_comparison_routes", "register_shared_login_routes",
    "build_resolved_settings", "build_routes", "install_middleware",
    "install_core_state", "install_shutdown_hooks",
    "install_platform_state", "install_auth_client_state",
    "install_workspace_claw_state", "install_b66_push_calendar_state",
    "create_app",
)

# Source-code order is NOT the runtime route order when private insertion uses
# routes[-1:-1]/[0:0]. Preserve the original registrar call order as well.
REGISTRATION_ORDER: tuple[str, ...] = (
    "register_util_routes", "register_opinion_news_routes",
    "register_ops_member_routes", "register_ops_round_score_routes",
    "register_ops_alert_routes", "register_ops_pc_self_heal_routes",
    "register_ops_news_routes", "register_pc_helper_version_routes",
    "register_admin_feedback_routes", "register_site_feedback_routes",
    "register_admin_routes", "register_auth_voice_routes",
    "register_auth_login_routes", "register_connector_routes",
    "register_project_document_routes", "register_chat_routes",
    "register_b66_routes", "register_web_xlsx_routes",
    "register_claw_routes", "register_calendar_routes",
    "register_pc_routes", "register_static_routes",
    "register_connector_enrollment_routes", "register_oracle_mesh_routes",
    "register_shared_auth_comparison_routes", "register_shared_login_routes",
)

# Basic public route signature for the unmodified factory; count is recorded
# in the baseline, not hardcoded in a fragile test.
PUBLIC_ROUTE_HEAD = ("/health", ("GET", "HEAD"))
STATIC_CATCH_ALL = "/"

def modules(selection: Iterable[ModuleType | str] | None = None) -> tuple[ModuleType, ...]:
    values = FACTORY_MODULES if selection is None else tuple(selection)
    return tuple(
        item if isinstance(item, ModuleType)
        else importlib.import_module(item if "." in item else f"app.{item}")
        for item in values
    )

def short_name(module: ModuleType) -> str:
    return module.__name__.rsplit(".", 1)[-1]

def factory_area_source() -> str:
    """Read the facade and every registered owner for existing source contracts."""
    return "\n\n".join(
        (APP_DIR / f"{name}.py").read_text(encoding="utf-8")
        for name in FACTORY_MODULES
    )

def syntax_tree(module: ModuleType) -> ast.Module:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"), filename=module.__file__)

def defined_names(module: ModuleType) -> set[str]:
    names: set[str] = set()
    for node in syntax_tree(module).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names

def definition_owner(name: str, selection: Iterable[ModuleType | str] | None = None) -> ModuleType:
    owners = [module for module in modules(selection) if name in defined_names(module)]
    if len(owners) != 1:
        raise AssertionError(f"{name}: expected one defining owner, got {[short_name(x) for x in owners]}")
    return owners[0]

def imported_factory_modules(module: ModuleType) -> tuple[str, ...]:
    """Inspect imports structurally; do not use raw source substring assertions."""
    targets: list[str] = []
    for node in ast.walk(syntax_tree(module)):
        if isinstance(node, ast.Import):
            targets.extend(alias.name.rsplit(".", 1)[-1]
                           for alias in node.names if alias.name.rsplit(".", 1)[-1].startswith("app_factory"))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.rsplit(".", 1)[-1].startswith("app_factory"):
                targets.append(node.module.rsplit(".", 1)[-1])
            elif node.module in ("app", None) and node.level <= 1:
                targets.extend(alias.name for alias in node.names if alias.name.startswith("app_factory"))
    return tuple(targets)

def runtime_global_reads(module: ModuleType) -> set[str]:
    """Count only LOAD_GLOBAL of functions really *defined* here, not facade aliases."""
    found: set[str] = set()
    for obj in vars(module).values():
        if getattr(obj, "__module__", None) != module.__name__ or not hasattr(obj, "__code__"):
            continue
        found.update(ins.argval for ins in dis.get_instructions(obj) if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME"))
    return found

def patch_targets(name: str, selection: Iterable[ModuleType | str] | None = None) -> tuple[ModuleType, ...]:
    selected = modules(selection)
    bound = tuple(m for m in selected if name in vars(m) and name in runtime_global_reads(m))
    if not bound:
        raise AssertionError(f"vacuous patch: no owner function loads {name!r} as a global")
    return bound

def patch_bound(monkeypatch, name: str, replacement, selection: Iterable[ModuleType | str] | None = None) -> None:
    """Patch all *actual execution owners*; never silently patch facade reexports."""
    for module in patch_targets(name, selection):
        monkeypatch.setattr(module, name, replacement)

def function_block(module: ModuleType, name: str) -> tuple[str, ast.AST]:
    """For later slice equality: exact lines plus AST node of the owner definition."""
    tree = syntax_tree(module)
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name]
    if len(nodes) != 1:
        raise AssertionError(f"{name} in {short_name(module)}: expected one definition")
    node = nodes[0]
    text = Path(module.__file__).read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(text[node.lineno - 1:node.end_lineno]), node
