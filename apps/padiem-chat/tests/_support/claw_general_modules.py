"""#7809 PR0 — claw_general 영역 레지스트리와 위치에 묶이지 않는 시험 도구.

``app/claw_general_routes.py`` 를 영역별 파일로 나누는 동안 시험이 "진입 파일 하나"를
전제로 하면 PR 마다 시험 수십 개를 고쳐야 한다. 이 모듈이 그 전제를 한곳에 모은다.

- ``CLAW_GENERAL_MODULES`` — 이 영역에 속한 app 모듈 이름. 영역 파일을 옮기는 PR 은
  여기에 한 줄만 더한다(진입점 포함). 가드 시험이 ``app/claw_general_*.py`` 와 같은지 본다.
- ``sources()`` / ``server_facts()`` — 소스 글자·AST 를 읽는 시험이 한 파일 대신 영역
  전체를 읽는다. 모듈 사이에 경계 함수를 끼워 함수 블록 자르기가 옆 파일로 번지지 않는다.
- ``patch_bound()`` / ``bound_patch()`` — 이름을 가진 **모든** 모듈에 patch 한다. 호출하는
  위치가 새 파일로 옮겨 가도 시험은 그대로 먹는다. 아무 모듈도 그 이름을 전역으로 읽지
  않으면(진입점에 다시 내보내기만 남은 경우 등) patch 가 조용히 빗나가므로 실패시킨다.
- ``find_attr()`` — 정의된 모듈이 어디든 그 이름의 값을 찾는다.

시험은 ``monkeypatch.setattr(<claw_general 모듈>, ...)`` 로 직접 patch 하지 않는다
(``test_7809_claw_general_split_guards`` 가 막는다).
"""
from __future__ import annotations

import ast
import contextlib
import functools
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Iterator
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[2] / "app"
TESTS_DIR = Path(__file__).resolve().parents[1]

ENTRY_MODULE = "claw_general_routes"

# 영역 파일을 옮기는 PR 은 이 튜플에 새 모듈 이름을 한 줄 더한다.
CLAW_GENERAL_MODULES: tuple[str, ...] = (
    ENTRY_MODULE,
    "claw_general_contract",
    "claw_general_stage",
    "claw_general_response",
    "claw_general_pc_intent",
    "claw_general_search",
    "claw_general_capabilities",
    "claw_general_conversation",
    "claw_general_catalog",
)

# ``claw_general_`` 접두사를 쓰지만 이 나누기와 무관한 app 파일.
NOT_PART_OF_SPLIT = frozenset({"claw_general_run_history"})

# ``claw_first_turn_authority`` 를 가져오는 app 파일의 정확한 집합(test_3933).
# 영역을 옮기는 PR 이 그 모듈을 가져오는 파일을 바꾸면 여기도 같이 고친다.
FIRST_TURN_AUTHORITY_IMPORTERS: tuple[str, ...] = (
    "claw_general_routes.py",
    "claw_general_conversation.py",
)

# 다른 파일(운영 코드 3곳·시험)이 claw_general_routes 에서 가져오거나 읽는 이름 44개.
# 영역 파일로 옮겨져도 진입점이 계속 내보내야 한다(가드가 본다).
ENTRY_EXPORTS: tuple[str, ...] = (
    "claw_general_capabilities",
    "_claw_general_pc_work_context",
    "_start_selectable_model_read",
    "_combine_system_context",
    "_MODEL_HOLD_ERROR_CODES",
    "_MODEL_HOLD_USER_MESSAGE",
    "CLAW_LIVE_REQUEST_HEADER",
    "CLAW_LIVE_REQUEST_MARKER",
    "MAX_CLAW_GENERAL_BODY_BYTES",
    "P01_ENGINE_REQUEST_ENVELOPE_BYTES",
    "claw_general_execute",
    "_owner_claw_context",
    "_record_completed_claw_result",
    "_save_claw_exchange",
    "_claw_custom_direct",
    "_claw_general_intake",
    "_claw_general_session_custom",
    "_claw_general_user_text",
    "_desktop_exception_question",
    "_requested_desktop_control",
    "_requested_desktop_task",
    "_requested_local_command",
    "_requested_local_desktop",
    "_requested_local_txt_path",
    "_requested_natural_pc_files",
    "_requested_natural_pc_query",
    "_requested_read_only_screen_view",
    "_claw_general_pc_branch",
    "_confirmed_staged_desktop_type",
    "_confirmed_staged_pc_command",
    "_dispatch_user_command_request",
    "_dispatch_user_desktop_request",
    "_dispatch_user_txt_request",
    "_stage_desktop_type_confirmation",
    "_stage_pc_command_confirmation",
    "_claw_general_quota_gate",
    "_claw_general_sse",
    "CLAW_EVIDENCE_MARKER",
    "CLAW_EVIDENCE_REQUEST_HEADER",
    "_claw_general_route_preflight",
    "_claw_public_search_grounding",
    "_project_search_sources",
    "CLAW_PUBLIC_SEARCH_STATE_FLAG",
    "_claw_stage",
)

# 낮은 단계만 가져올 수 있다(같은 단계끼리도 금지). 진입점은 맨 위.
MODULE_LEVELS: dict[str, int] = {
    "claw_general_contract": 0,
    "claw_general_stage": 0,
    "claw_general_response": 0,
    "claw_general_pc_intent": 0,
    "claw_general_search": 0,
    "claw_general_capabilities": 0,
    "claw_general_conversation": 0,
    "claw_general_catalog": 1,
    "claw_general_preflight": 1,
    "claw_general_intake": 1,
    "claw_general_context": 1,
    "claw_general_quota": 1,
    "claw_general_pc_desktop": 1,
    "claw_general_pc_command": 1,
    "claw_general_pc_branch": 2,
    ENTRY_MODULE: 3,
}

# 이 영역은 chat 스트림·B14 직접 호출·B66·수동 접수 흐름을 가져오지 않는다.
FORBIDDEN_IMPORT_NAMES = frozenset({"chat_routes", "b14_client"})
FORBIDDEN_IMPORT_PREFIXES = ("b66_", "manual_intake")

# 모듈 사이에 끼우는 경계. 이름이 ``_claw_general_`` 로 시작하지 않아 헬퍼 목록에 안 잡히고,
# ``\ndef `` 로 끝나는 블록 자르기가 옆 파일 머리말까지 번지는 것을 막는다.
MODULE_BOUNDARY = "\n\n\ndef _module_boundary() -> None:\n    return None\n\n\n"

ModuleSelection = Iterable[Any] | None


def _import(name: str) -> ModuleType:
    return importlib.import_module(name if "." in name else f"app.{name}")


def modules(selection: ModuleSelection = None) -> list[ModuleType]:
    """선택한(기본은 레지스트리) 모듈 객체들. 문자열 이름이나 모듈 객체를 받는다."""
    items = CLAW_GENERAL_MODULES if selection is None else tuple(selection)
    return [item if isinstance(item, ModuleType) else _import(item) for item in items]


def short_name(module: ModuleType) -> str:
    return module.__name__.rsplit(".", 1)[-1]


def source_of(module: ModuleType) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


@functools.lru_cache(maxsize=None)
def _tree(path: str) -> ast.Module:
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def tree_of(module: ModuleType) -> ast.Module:
    return _tree(str(module.__file__))


def sources(selection: ModuleSelection = None) -> str:
    """영역 전체의 소스 글자. 소스 글자를 읽는 시험은 한 파일 대신 이것을 읽는다."""
    return MODULE_BOUNDARY.join(source_of(module) for module in modules(selection))


def defined_names(module: ModuleType) -> set[str]:
    """최상위에서 정의한 이름(def·class·할당). 다시 내보낸 import 는 뺀다."""
    names: set[str] = set()
    for node in tree_of(module).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def function_definitions(name: str, selection: ModuleSelection = None) -> list[tuple[str, ast.AST]]:
    """이름이 같은 최상위 함수 정의를 영역 전체에서 모은다((모듈 이름, 노드))."""
    found: list[tuple[str, ast.AST]] = []
    for module in modules(selection):
        for node in tree_of(module).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                found.append((short_name(module), node))
    return found


def find_attr(name: str, selection: ModuleSelection = None) -> Any:
    """그 이름을 **정의한** 모듈의 값. 어디에 있든 시험은 같은 호출로 얻는다."""
    owners = [m for m in modules(selection) if name in defined_names(m)]
    if len(owners) != 1:
        raise AssertionError(
            f"{name!r} must be defined by exactly one claw_general module, "
            f"found {[short_name(m) for m in owners]}"
        )
    return getattr(owners[0], name)


def server_facts(selection: ModuleSelection = None) -> dict[str, set]:
    """test_3790 같은 AST 사실 시험용: 영역 전체의 사실을 합집합으로."""
    from _support.verified_model_choices import server_facts as module_facts

    merged: dict[str, set] = {}
    for module in modules(selection):
        for key, value in module_facts(short_name(module)).items():
            merged.setdefault(key, set()).update(value)
    return merged


# ── 헛 patch 탐지 ────────────────────────────────────────────────────────────


def _iter_scope(node: ast.AST) -> Iterator[ast.AST]:
    """함수 하나의 범위: 안쪽 함수·람다 본문은 들어가지 않고 그 노드만 돌려준다."""
    for child in ast.iter_child_nodes(node):
        yield child
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            # 안쪽 정의의 데코레이터·기본값은 바깥 범위에서 실행된다.
            if isinstance(child, ast.ClassDef):
                for part in (*child.decorator_list, *child.bases):
                    yield from ast.walk(part)
            else:
                for part in (*getattr(child, "decorator_list", ()), *child.args.defaults,
                             *(d for d in child.args.kw_defaults if d is not None)):
                    yield from ast.walk(part)
            continue
        yield from _iter_scope(child)


def _own_bound(function: ast.AST) -> set[str]:
    bound: set[str] = set()
    args = function.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        bound.add(arg.arg)
    for arg in (args.vararg, args.kwarg):
        if arg is not None:
            bound.add(arg.arg)
    declared_global: set[str] = set()
    body = [function.body] if isinstance(function, ast.Lambda) else function.body
    for statement in body:
        for node in (statement, *_iter_scope(statement)):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.Global):
                declared_global.update(node.names)
    return bound - declared_global


def _function_loads(function: ast.AST, outer: frozenset[str], loads: set[str]) -> None:
    bound = outer | _own_bound(function)
    body = [function.body] if isinstance(function, ast.Lambda) else function.body
    for statement in body:
        for node in (statement, *_iter_scope(statement)):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
                loads.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                _function_loads(node, frozenset(bound), loads)


@functools.lru_cache(maxsize=None)
def _runtime_global_reads(path: str) -> frozenset[str]:
    """요청이 지나갈 때 실행되는 함수 본문이 전역으로 읽는 이름(지역 변수·지역 import 제외)."""
    loads: set[str] = set()
    for node in _tree(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _function_loads(node, frozenset(), loads)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _function_loads(member, frozenset(), loads)
    return frozenset(loads)


def runtime_global_reads(module: ModuleType) -> frozenset[str]:
    return _runtime_global_reads(str(module.__file__))


def patch_targets(name: str, selection: ModuleSelection = None) -> list[ModuleType]:
    """patch 가 실제로 먹는 모듈들. 헛 patch 이면 AssertionError.

    - 그 이름을 전역으로 가진 모듈이 하나도 없으면: 잘못된 이름이거나 다른 모듈에 있다.
    - 가진 모듈은 있는데 어느 것도 함수 본문에서 읽지 않으면: 다시 내보내기만 남은 이름이라
      patch 해도 실제 호출은 다른 모듈의 바인딩을 쓴다(조용히 효과 없음).
    """
    mods = modules(selection)
    bound = [m for m in mods if name in vars(m)]
    if not bound:
        raise AssertionError(
            f"patch target {name!r} is not a global of any claw_general module "
            f"{[short_name(m) for m in mods]}"
        )
    if not any(name in runtime_global_reads(m) for m in bound):
        raise AssertionError(
            f"vacuous patch: {name!r} is bound in {[short_name(m) for m in bound]} but no function "
            "there reads it as a global, so patching it changes nothing; patch the module that "
            "really calls it"
        )
    return bound


def patch_bound(monkeypatch: Any, name: str, value: Any, *, modules: ModuleSelection = None) -> list[ModuleType]:
    """이름을 가진 모든 claw_general 모듈에 monkeypatch.setattr (호출하는 모든 위치)."""
    targets = patch_targets(name, modules)
    for module in targets:
        monkeypatch.setattr(module, name, value)
    return targets


@contextlib.contextmanager
def bound_patch(name: str, new: Any = mock.DEFAULT, *, modules: ModuleSelection = None, **mock_kwargs: Any) -> Iterator[Any]:
    """``unittest.mock.patch`` 짝: 같은 대역(mock)을 모든 모듈에 깔고 그 대역을 돌려준다."""
    targets = patch_targets(name, modules)
    with contextlib.ExitStack() as stack:
        first, *rest = targets
        replacement = stack.enter_context(mock.patch.object(first, name, new, **mock_kwargs))
        for module in rest:
            stack.enter_context(mock.patch.object(module, name, replacement))
        yield replacement


# ── 시험 파일을 훑는 정적 검사 ───────────────────────────────────────────────

_PATCH_CALLEES = ("setattr", "delattr", "patch", "object", "setitem")


def _claw_general_module_name(dotted: str) -> str | None:
    for part in dotted.split("."):
        if part.startswith("claw_general_") and part not in NOT_PART_OF_SPLIT:
            return part
    return None


def _module_aliases(tree: ast.AST) -> set[str]:
    """이 시험 파일에서 claw_general 모듈 객체를 가리키는 이름들."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _claw_general_module_name(alias.name):
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if _claw_general_module_name(node.module or ""):
                continue  # 이름을 가져온 것이지 모듈 객체가 아니다
            for alias in node.names:
                if _claw_general_module_name(alias.name):
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            value = node.value
            if (isinstance(value, ast.Call) and value.args
                    and isinstance(value.args[0], ast.Constant)
                    and isinstance(value.args[0].value, str)
                    and _claw_general_module_name(value.args[0].value)):
                aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif (isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Constant)
                    and isinstance(value.slice.value, str)
                    and _claw_general_module_name(value.slice.value)):
                aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return aliases


def _is_patch_call(call: ast.Call) -> bool:
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return name in _PATCH_CALLEES


def direct_patches(tree: ast.AST) -> list[tuple[int, str]]:
    """claw_general 모듈에 monkeypatch/mock.patch 로 직접 거는 곳((줄, 코드))."""
    aliases = _module_aliases(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args and _is_patch_call(node)):
            continue
        first = node.args[0]
        hit = False
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            hit = bool(_claw_general_module_name(first.value))
        elif isinstance(first, (ast.Name, ast.Attribute)):
            hit = ast.unparse(first) in aliases or bool(
                _claw_general_module_name(ast.unparse(first)) and isinstance(first, ast.Attribute)
            )
        if hit:
            found.append((node.lineno, ast.unparse(node)[:120]))
    return found


def helper_patch_names(tree: ast.AST) -> list[tuple[int, str]]:
    """``patch_bound``·``bound_patch`` 호출이 이름으로 쓴 문자열 리터럴((줄, 이름))."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if callee == "patch_bound" and len(node.args) >= 2:
            name_arg = node.args[1]
        elif callee == "bound_patch" and node.args:
            name_arg = node.args[0]
        else:
            continue
        if isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str):
            found.append((node.lineno, name_arg.value))
    return found


def iter_test_trees(skip: Iterable[str] = (), needle: str = "claw_general") -> Iterator[tuple[str, ast.AST]]:
    """``needle`` 글자가 있는 시험 파일만 파싱해서 돌려준다(수천 개를 다 파싱하지 않는다)."""
    skipped = set(skip)
    for path in sorted(TESTS_DIR.rglob("*.py")):
        relative = path.relative_to(TESTS_DIR).as_posix()
        if relative in skipped or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8-sig")
        if needle not in text:
            continue
        try:
            yield relative, ast.parse(text)
        except SyntaxError:
            continue


def imported_claw_general_modules(path: Path) -> list[tuple[str, int, bool]]:
    """한 모듈 파일이 가져오는 ``claw_general_*`` 모듈((이름, 줄, 함수 안인가))."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nested: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested.update(id(child) for child in ast.walk(node))
    found: list[tuple[str, int, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            target = _claw_general_module_name(node.module or "")
            if target:
                found.append((target, node.lineno, id(node) in nested))
            elif node.level and (node.module or "") == "":
                for alias in node.names:
                    if _claw_general_module_name(alias.name):
                        found.append((alias.name, node.lineno, id(node) in nested))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target = _claw_general_module_name(alias.name)
                if target:
                    found.append((target, node.lineno, id(node) in nested))
    return found


def imported_module_names(path: Path) -> list[tuple[str, int]]:
    """한 모듈 파일이 가져오는 app 모듈의 마지막 이름((이름, 줄))."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                if module:
                    found.append((module.split(".")[0], node.lineno))
                else:
                    found.extend((alias.name, node.lineno) for alias in node.names)
            elif module.startswith("app."):
                found.append((module.split(".")[1], node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    found.append((alias.name.split(".")[1], node.lineno))
    return found
