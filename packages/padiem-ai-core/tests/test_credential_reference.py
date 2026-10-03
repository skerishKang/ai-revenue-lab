"""Tests for the shared credential binding-name grammar (#2103 ACT-1).

Covers the ACT-1 acceptance points:
1. the canonical grammar is a single shared constant
2. stdlib-only, network-free, environment-free, secret-free module
3. failure is closed: non-conforming names are rejected and never normalized
4. rejection messages never echo the submitted value
5. no credential-mode enum unification happens in this module
6. current Business 14 platform secret bindings are already a valid subset
7. current Control Plane product routes are anonymous and carry no binding
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import padiem_ai_core.credential_reference as credential_reference
from padiem_ai_core.credential_reference import (
    CREDENTIAL_BINDING_MAX_LENGTH,
    CREDENTIAL_BINDING_MIN_LENGTH,
    CREDENTIAL_BINDING_PATTERN,
    CredentialReferenceError,
    RAW_SECRET_IN_CONTRACT,
    validate_credential_binding_name,
)

MODULE_PATH = Path(credential_reference.__file__)
PACKAGE_DIR = MODULE_PATH.parent
REPO_ROOT = Path(__file__).resolve().parents[3]

B14_PILOT_DIR = REPO_ROOT / "apps" / "korean-ai-platform" / "app" / "pilot"
CONTROL_PLANE_TIER_ROUTES = (
    REPO_ROOT
    / "packages"
    / "padiem-control-plane"
    / "padiem_control_plane"
    / "product_tier_routes.py"
)

# Binding names actually registered by Business 14 on current main.
CURRENT_B14_BINDINGS = (
    "PADIEM_POOLSIDE_API_KEY",
    "PADIEM_SENSENOVA_API_KEY",
)

# Engine-owned platform tool credentials follow the same binding-name doctrine.
CURRENT_ENGINE_BINDINGS = (
    "PADIEM_ENGINE_FIRECRAWL_API_KEY",
    "PADIEM_ENGINE_DAUM_REST_API_KEY",
)

# Generated/vendored directories that may appear inside the consuming lanes
# during CI (uv virtualenvs, pywrangler vendoring, caches) are not lane source.
LANE_SCAN_SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tmp",
    "python_modules",
}

REJECTED_BINDINGS = (
    "",
    "A",
    "AB",
    "A" * 129,
    "PADIEM_POOLSIDE_API_KEY ",
    " PADIEM_POOLSIDE_API_KEY",
    "padiem_poolside_api_key",
    "PadiemPoolsideApiKey",
    "1ABC",
    "_ABC",
    "ABC DEF",
    "ABC-DEF",
    "ABC.DEF",
    "ABC,DEF",
    "ABC\nDEF",
    "kilo/poolside-laguna-s-2.1-free",
    "agent:b54:kilo@1",
    "connector:b54:kilo:default@1",
    "sk-live-abcdef",
    "Bearer PADIEM_POOLSIDE_API_KEY",
)


# A. canonical grammar
def test_pattern_constant_is_the_shared_grammar() -> None:
    assert CREDENTIAL_BINDING_PATTERN == r"^[A-Z][A-Z0-9_]{2,127}$"
    assert CREDENTIAL_BINDING_MIN_LENGTH == 3
    assert CREDENTIAL_BINDING_MAX_LENGTH == 128


def test_minimal_and_maximal_lengths_are_accepted() -> None:
    assert validate_credential_binding_name("ABC") == "ABC"
    assert validate_credential_binding_name("A" * 128) == "A" * 128


@pytest.mark.parametrize("name", CURRENT_B14_BINDINGS + CURRENT_ENGINE_BINDINGS)
def test_registered_lane_bindings_satisfy_the_shared_grammar(name: str) -> None:
    assert validate_credential_binding_name(name) is name


@pytest.mark.parametrize("name", REJECTED_BINDINGS)
def test_non_conforming_bindings_fail_closed(name: str) -> None:
    with pytest.raises(CredentialReferenceError):
        validate_credential_binding_name(name)


@pytest.mark.parametrize(
    "value",
    [None, 0, 0.0, True, b"PADIEM_POOLSIDE_API_KEY", ["PADIEM_POOLSIDE_API_KEY"], {}],
)
def test_non_string_input_fails_closed(value: object) -> None:
    with pytest.raises(CredentialReferenceError):
        validate_credential_binding_name(value)


def test_rejection_is_a_value_error_and_names_the_violation() -> None:
    for name, fragment in (
        ("", "must not be empty"),
        ("AB", "shorter than"),
        ("A" * 129, "longer than"),
        ("abc", "uppercase letter"),
    ):
        with pytest.raises(CredentialReferenceError, match=fragment):
            validate_credential_binding_name(name)
    with pytest.raises(ValueError):
        validate_credential_binding_name("abc")


def test_rejection_never_echoes_the_submitted_value() -> None:
    secret_shaped_values = (
        "sk-live-abcdef012345678901234567890123456789",
        "sk-live-abcdef",
        "padiem_poolside_api_key",
    )
    for value in secret_shaped_values:
        with pytest.raises(CredentialReferenceError) as caught:
            validate_credential_binding_name(value)
        assert value not in str(caught.value)


def test_valid_name_is_returned_unchanged_without_normalization() -> None:
    name = "PADIEM_POOLSIDE_API_KEY"
    assert validate_credential_binding_name(name) is name


# B. module purity: stdlib only, no network, no environment, no secrets
FORBIDDEN_MODULES = {
    "os",
    "socket",
    "subprocess",
    "shutil",
    "urllib",
    "http",
    "httpx",
    "requests",
    "asyncio",
    "pathlib",
    "pickle",
    "hashlib",
    "secrets",
    "random",
    "base64",
}


def test_module_imports_are_standard_library_only() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"__future__", "re"}
    assert imported.isdisjoint(FORBIDDEN_MODULES)


def test_module_performs_no_env_network_or_secret_access() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    attribute_calls = {
        (node.func.value.id, node.func.attr)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }

    forbidden_calls = {
        ("os", "environ"),
        ("os", "getenv"),
        ("os", "setenv"),
        ("os", "putenv"),
        ("socket", "create_connection"),
        ("subprocess", "run"),
    }
    assert forbidden_calls.isdisjoint(attribute_calls)
    for forbidden in ("eval(", "exec(", "open("):
        assert forbidden not in source


def test_module_exposes_no_secret_material() -> None:
    assert RAW_SECRET_IN_CONTRACT is False
    public_names = set(credential_reference.__dict__)
    assert public_names.isdisjoint(
        {"CREDENTIAL_REFERENCE", "BYOK_KEY", "API_KEY", "SECRET", "SECRET_VALUE"}
    )


def test_module_defines_no_credential_mode_vocabulary() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    class_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    class_names = {node.name for node in class_nodes}
    assert class_names == {"CredentialReferenceError"}
    enum_bases = {
        base for node in class_nodes for base in node.bases if "Enum" in ast.unparse(base)
    }
    assert enum_bases == set()


def test_module_has_no_state_mutation_surface() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert function_names == {"validate_credential_binding_name"}


# C. authority boundary of the export
def test_shared_names_are_exported_from_the_package_root() -> None:
    import padiem_ai_core as core

    for name in (
        "CREDENTIAL_BINDING_PATTERN",
        "CredentialReferenceError",
        "RAW_SECRET_IN_CONTRACT",
        "validate_credential_binding_name",
    ):
        assert name in core.__all__
        assert name in vars(core)
        assert getattr(core, name) == getattr(credential_reference, name)


# D. parity with the two consuming lanes (source-level, no runtime import edge)
def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _resolve_string(node: ast.AST | None, constants: dict[str, str]) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _keyword(node: ast.Call, name: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


def test_business_14_declared_platform_secret_bindings_are_a_shared_subset() -> None:
    """Every non-empty binding Business 14 declares already satisfies the grammar."""
    pilot_modules = sorted(B14_PILOT_DIR.glob("*.py"))
    assert pilot_modules, f"expected Business 14 pilot modules under {B14_PILOT_DIR}"

    declared: dict[str, list[str]] = {}
    for module_path in pilot_modules:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        constants = _module_string_constants(tree)
        for call in _calls_named(tree, "PlatformProviderSpec"):
            binding = _resolve_string(_keyword(call, "credential_binding_name"), constants)
            if binding:
                declared.setdefault(module_path.name, []).append(binding)

    assert any(declared.values()), "expected at least one platform secret binding"
    for module_name, bindings in declared.items():
        for binding in bindings:
            assert validate_credential_binding_name(binding) is binding, (
                f"{module_name}: binding violates the shared grammar"
            )


def test_business_14_keyless_routes_carry_no_binding_name() -> None:
    """``none``-credential routes must not claim a platform secret binding."""
    for module_path in sorted(B14_PILOT_DIR.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        constants = _module_string_constants(tree)
        for call in _calls_named(tree, "PlatformProviderSpec"):
            source = _keyword(call, "credential_source")
            binding = _resolve_string(_keyword(call, "credential_binding_name"), constants)
            is_keyless = (
                (isinstance(source, ast.Constant) and source.value == "none")
                or (isinstance(source, ast.Attribute) and source.attr == "NONE")
            )
            if is_keyless:
                assert binding in (None, ""), (
                    f"{module_path.name}: keyless route declares a binding name"
                )


def _control_plane_routes() -> list[dict[str, str | None]]:
    tree = ast.parse(CONTROL_PLANE_TIER_ROUTES.read_text(encoding="utf-8"))
    constants = _module_string_constants(tree)
    enum_values: dict[str, str] = {}
    defaults: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name == "ProductCredentialMode":
            for sub in node.body:
                if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Constant):
                    for target in sub.targets:
                        if isinstance(target, ast.Name):
                            enum_values[target.id] = str(sub.value.value)
        elif node.name == "ProductTierRoute":
            for sub in node.body:
                if (
                    isinstance(sub, ast.AnnAssign)
                    and sub.target.id == "credential_mode"
                    and isinstance(sub.value, ast.Attribute)
                ):
                    defaults["credential_mode"] = enum_values.get(sub.value.attr)

    routes: list[dict[str, str | None]] = []
    for call in _calls_named(tree, "ProductTierRoute"):
        mode_node = _keyword(call, "credential_mode")
        if isinstance(mode_node, ast.Attribute):
            mode = enum_values.get(mode_node.attr)
        elif isinstance(mode_node, ast.Constant):
            mode = str(mode_node.value)
        else:
            mode = defaults.get("credential_mode")
        routes.append(
            {
                "mode": mode,
                "binding": _resolve_string(_keyword(call, "credential_binding"), constants),
            }
        )
    return routes


def test_control_plane_declared_bindings_satisfy_shared_grammar_and_sublimit() -> None:
    """Product bindings stay a subset of the shared grammar plus their <=63 sublimit."""
    for route in _control_plane_routes():
        if route["binding"] is None:
            continue
        binding = validate_credential_binding_name(route["binding"])
        assert binding == route["binding"]
        assert len(binding) <= 64, "product declaration keeps its <=63-char sublimit"


def test_control_plane_anonymous_routes_carry_no_binding_name() -> None:
    routes = _control_plane_routes()
    assert routes, "expected product tier route declarations"
    for route in routes:
        assert route["mode"] is not None, "every route declares an explicit credential mode"
        if route["mode"] == "anonymous":
            assert route["binding"] is None, (
                "anonymous product routes must not carry a credential binding"
            )


def test_no_declared_binding_violates_the_shared_minimum_length() -> None:
    """The shared 3-char minimum is already respected by every current declaration."""
    bindings: list[str] = []
    for module_path in sorted(B14_PILOT_DIR.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        constants = _module_string_constants(tree)
        for call in _calls_named(tree, "PlatformProviderSpec"):
            binding = _resolve_string(_keyword(call, "credential_binding_name"), constants)
            if binding:
                bindings.append(binding)
    bindings.extend(route["binding"] for route in _control_plane_routes() if route["binding"])
    assert bindings, "expected at least one declared credential binding"
    assert all(len(binding) >= CREDENTIAL_BINDING_MIN_LENGTH for binding in bindings)


# E. scope guards: this module changes no lane and no runtime behavior
def test_consuming_lane_sources_are_unmodified_by_this_contract() -> None:
    """The contract lives only in Core; no lane source references it yet."""
    lane_roots = (
        REPO_ROOT / "apps",
        REPO_ROOT / "packages" / "padiem-control-plane",
    )
    references = [
        str(path.relative_to(REPO_ROOT))
        for lane_root in lane_roots
        for path in lane_root.rglob("*.py")
        if not any(part in LANE_SCAN_SKIP_PARTS for part in path.parts)
        and "credential_reference" in path.read_text(encoding="utf-8")
    ]
    assert not references
