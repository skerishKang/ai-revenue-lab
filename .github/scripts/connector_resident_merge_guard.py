"""#4139 — source-only guard against losing the reviewed Windows Resident safety seam.

This checks structural integration invariants, not actual Broker connectivity.
The first, unintegrated main tree lacks resident_launch.py and is intentionally
allowed. Once the launch plan is present, conflicting Windows PRs must retain
the refusal-before-spawn and DPAPI-resume contracts.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

WIN = Path("apps/claw-connect/claw_connect")
KAGENT = Path("apps/korean-ai-code-agent/src/kagent")


def _member(tree: ast.AST, class_name: str, method: str) -> ast.AST | None:
    for node in getattr(tree, "body", ()):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return next(
                (child for child in node.body
                 if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and child.name == method), None
            )
    return None


def _function(tree: ast.AST, name: str) -> ast.AST | None:
    return next(
        (node for node in getattr(tree, "body", ())
         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name),
        None,
    )


def _call(node: ast.AST | None, attribute: str) -> bool:
    return node is not None and any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == attribute
        for child in ast.walk(node)
    )


def _name_call(node: ast.AST | None, name: str) -> bool:
    return node is not None and any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == name
        for child in ast.walk(node)
    )


def _catches(node: ast.AST | None, name: str) -> bool:
    return node is not None and any(
        isinstance(child, ast.ExceptHandler)
        and isinstance(child.type, ast.Name)
        and child.type.id == name
        for child in ast.walk(node)
    )


def _declining_env_refuses(start: ast.AST | None) -> bool:
    if start is None:
        return False
    for node in ast.walk(start):
        if not isinstance(node, ast.If):
            continue
        condition = node.test
        if not (
            isinstance(condition, ast.Compare)
            and isinstance(condition.left, ast.Name)
            and condition.left.id == "env"
            and len(condition.ops) == 1
            and isinstance(condition.ops[0], ast.Is)
            and len(condition.comparators) == 1
            and isinstance(condition.comparators[0], ast.Constant)
            and condition.comparators[0].value is None
        ):
            continue
        branch = ast.Module(body=node.body, type_ignores=[])
        refused = any(
            isinstance(child, ast.Raise)
            and isinstance(child.exc, ast.Call)
            and isinstance(child.exc.func, ast.Name)
            and child.exc.func.id == "ResidentLaunchRefused"
            for child in ast.walk(branch)
        )
        if refused and not _call(branch, "_popen"):
            return True
    return False


def audit(root: Path) -> tuple[str, list[str]]:
    """Return one of NOT_INTEGRATED / PASS / FAIL plus bounded invariant names."""
    if not (root / WIN / "resident_launch.py").is_file():
        return "NOT_INTEGRATED", []

    def parse(path: Path) -> ast.AST | None:
        try:
            return ast.parse((root / path).read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, UnicodeError):
            return None

    issues: list[str] = []
    supervisor = parse(WIN / "resident_supervisor.py")
    runtime = parse(WIN / "runtime.py")
    resident = parse(KAGENT / "local_agent_resident_process.py")
    binding_file = root / KAGENT / "local_agent_device_binding_store.py"

    start = _member(supervisor, "ResidentSupervisor", "start") if supervisor else None
    if supervisor is None or not any(
        isinstance(item, ast.ClassDef) and item.name == "ResidentLaunchRefused"
        for item in getattr(supervisor, "body", ())
    ) or not _declining_env_refuses(start):
        issues.append("supervisor_provider_none_must_refuse_before_spawn")

    init = _member(runtime, "ConnectApp", "__init__") if runtime else None
    wired = init is not None and any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ResidentSupervisor"
        and any(
            kw.arg == "env"
            and isinstance(kw.value, ast.Attribute)
            and kw.value.attr == "_resident_environment"
            for kw in node.keywords
        )
        for node in ast.walk(init)
    )
    if not wired:
        issues.append("connect_app_supervisor_requires_env_provider")

    for method, invoked in (
        ("start_registered_resident", "start"),
        ("reconnect", "restart"),
        ("toggle_pause", "start"),
    ):
        fn = _member(runtime, "ConnectApp", method) if runtime else None
        if not (_call(fn, invoked) and _catches(fn, "ResidentLaunchRefused")):
            issues.append(f"{method}_must_handle_spawn_refusal")

    main = _function(resident, "main") if resident else None
    resume = _function(resident, "resume_registered_binding") if resident else None
    if not (_name_call(main, "resume_registered_binding")
            and _name_call(resume, "ProtectedDeviceBindingStore")):
        issues.append("resident_must_restore_canonical_protected_binding")
    if not binding_file.is_file():
        issues.append("canonical_protected_binding_store_missing")

    return ("FAIL" if issues else "PASS"), issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    state, issues = audit(args.repo_root.resolve())
    print(f"RESIDENT_MERGE_GUARD={state}")
    for item in issues:
        print(f"INVARIANT_FAILED={item}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
