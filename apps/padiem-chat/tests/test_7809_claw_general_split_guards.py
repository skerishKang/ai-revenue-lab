"""#7809 PR0 — claw_general 나누기 준비 가드.

``app/claw_general_routes.py`` 를 영역 파일로 나누는 PR 들이 시험을 조용히 약하게 만들지
못하게 하는 가드와, 그 가드·도구 자신의 증거 시험이다. 앱 코드는 바꾸지 않는다.

가드
1. 레지스트리 == ``app/claw_general_*.py`` (등록을 잊으면 실패)
2. 헛 patch 탐지(정적) — ``patch_bound``/``bound_patch`` 가 쓰는 이름은 영역 안 어느 모듈이
   전역으로 가지고 함수 본문에서 읽어야 한다. 다시 내보내기만 남은 이름이면 실패한다.
3. 직접 patch 금지 — 시험은 claw_general 모듈 객체에 monkeypatch/mock.patch 로 직접 걸지 않는다.
   직접 걸면 호출 위치가 옮겨 간 뒤 에러 없이 효과가 사라진다.
4. import 방향 — 낮은 단계가 높은 단계를 가져오지 않고, chat 스트림·B14 직접 호출·B66·수동 접수를
   가져오지 않는다(글자 금지어 시험의 구조 짝).

도구 증거: 가짜 모듈 한 쌍으로 헛 patch 를 실제로 잡는지, patch_bound 가 호출하는 모듈까지
닿는지 보인다(앱 파일을 건드리지 않고 "나눈 뒤"의 모양을 재현).
"""
from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path
from types import ModuleType

import pytest

from _support import claw_general_modules as cg

_SELF = "test_7809_claw_general_split_guards.py"
_SUPPORT = "_support/claw_general_modules.py"
_counter = itertools.count()


# ── 가드 1·4: 레지스트리와 import 방향 ────────────────────────────────────────


def test_registry_matches_the_claw_general_files():
    files = {
        path.stem for path in cg.APP_DIR.glob("claw_general_*.py")
        if path.stem not in cg.NOT_PART_OF_SPLIT
    }
    assert set(cg.CLAW_GENERAL_MODULES) == files, (
        "register the new app/claw_general_*.py file in CLAW_GENERAL_MODULES "
        "(tests/_support/claw_general_modules.py)"
    )
    assert len(set(cg.CLAW_GENERAL_MODULES)) == len(cg.CLAW_GENERAL_MODULES)


def test_every_registered_module_has_a_level_and_the_entry_is_the_highest():
    assert set(cg.CLAW_GENERAL_MODULES) <= set(cg.MODULE_LEVELS)
    assert cg.ENTRY_MODULE in cg.CLAW_GENERAL_MODULES
    assert cg.MODULE_LEVELS[cg.ENTRY_MODULE] == max(cg.MODULE_LEVELS.values())


def test_first_turn_authority_importer_list_names_registered_files_only():
    registered = {name + ".py" for name in cg.CLAW_GENERAL_MODULES}
    assert set(cg.FIRST_TURN_AUTHORITY_IMPORTERS) <= registered


@pytest.mark.parametrize("name", cg.CLAW_GENERAL_MODULES)
def test_imports_only_point_down_the_levels(name):
    level = cg.MODULE_LEVELS[name]
    path = cg.APP_DIR / (name + ".py")
    offenders = []
    for target, lineno, _nested in cg.imported_claw_general_modules(path):
        if target not in cg.MODULE_LEVELS:
            offenders.append(f"{name}.py:{lineno} imports unknown claw_general module {target}")
        elif cg.MODULE_LEVELS[target] >= level:
            offenders.append(
                f"{name}.py:{lineno} imports {target} (level {cg.MODULE_LEVELS[target]}) "
                f"from level {level}"
            )
    assert offenders == []


@pytest.mark.parametrize("name", cg.CLAW_GENERAL_MODULES)
def test_the_area_never_imports_chat_stream_b14_b66_or_manual_intake(name):
    path = cg.APP_DIR / (name + ".py")
    offenders = [
        f"{name}.py:{lineno} imports {module}"
        for module, lineno in cg.imported_module_names(path)
        if module in cg.FORBIDDEN_IMPORT_NAMES
        or module.startswith(cg.FORBIDDEN_IMPORT_PREFIXES)
    ]
    assert offenders == []


# ── 가드 2·3: 시험 파일 전체를 훑는다 ───────────────────────────────────────────


def test_every_patch_bound_name_is_a_global_that_a_function_reads():
    """헛 patch 탐지: 이름이 없거나 다시 내보내기만 남았으면 patch 는 아무 일도 안 한다."""
    failures = []
    checked = 0
    for relative, tree in cg.iter_test_trees(skip={_SELF, _SUPPORT}):
        for lineno, name in cg.helper_patch_names(tree):
            checked += 1
            try:
                cg.patch_targets(name)
            except AssertionError as error:
                failures.append(f"{relative}:{lineno}: {error}")
    assert checked > 30, "the scan must reach the converted tests"
    assert failures == []


def test_no_test_patches_a_claw_general_module_directly():
    """직접 patch 는 호출 위치가 옮겨 가면 에러 없이 효과가 사라진다. 도우미를 쓴다."""
    offenders = []
    for relative, tree in cg.iter_test_trees(skip={_SELF, _SUPPORT}):
        for lineno, code in cg.direct_patches(tree):
            offenders.append(f"{relative}:{lineno}: {code}")
    assert offenders == [], (
        "use tests/_support/claw_general_modules.patch_bound / bound_patch instead"
    )


# ── 도구 증거: 가짜 모듈 한 쌍으로 "나눈 뒤"의 모양을 재현 ───────────────────────


def _load(tmp_path: Path, name: str, source: str) -> ModuleType:
    unique = f"_pr0_{name}_{next(_counter)}"
    path = tmp_path / f"{unique}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(unique, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def split_pair(tmp_path):
    """leaf 가 helper 를 정의하고 호출하며, entry 는 이름만 다시 내보낸다."""
    leaf = _load(tmp_path, "leaf", "def helper():\n    return 'real'\n\n\ndef run():\n    return helper()\n")
    entry = _load(tmp_path, "entry", "def go(leaf):\n    return leaf.run()\n")
    entry.helper = leaf.helper  # 다시 내보내기: 있지만 아무 함수도 읽지 않는다
    yield leaf, entry
    for module in (leaf, entry):
        sys.modules.pop(module.__name__, None)


def test_a_reexport_only_patch_is_rejected_as_vacuous(split_pair):
    leaf, entry = split_pair
    with pytest.raises(AssertionError, match="vacuous patch"):
        cg.patch_targets("helper", [entry])
    with pytest.raises(AssertionError, match="not a global of any"):
        cg.patch_targets("no_such_name", [leaf, entry])


def test_patch_bound_reaches_the_module_that_really_calls(split_pair, monkeypatch):
    leaf, entry = split_pair
    fake = lambda: "fake"  # noqa: E731
    # 옛 방식: 다시 내보낸 이름에 직접 patch — 성공하지만 실제 호출은 그대로다.
    monkeypatch.setattr(entry, "helper", fake)
    assert entry.go(leaf) == "real", "the old-style patch silently changes nothing"
    monkeypatch.undo()
    # 도우미: 호출하는 모듈까지 patch 한다.
    targets = cg.patch_bound(monkeypatch, "helper", fake, modules=[entry, leaf])
    assert {m.__name__ for m in targets} == {leaf.__name__, entry.__name__}
    assert entry.go(leaf) == "fake"
    monkeypatch.undo()
    assert entry.go(leaf) == "real"


def test_bound_patch_installs_one_shared_mock_in_every_binding(split_pair):
    leaf, entry = split_pair
    with cg.bound_patch("helper", modules=[entry, leaf], return_value="mocked") as helper:
        assert entry.helper is helper and leaf.helper is helper
        assert entry.go(leaf) == "mocked"
        helper.assert_called_once()
    assert entry.go(leaf) == "real"


def test_a_local_import_does_not_count_as_a_global_read(tmp_path):
    """claw_general_capabilities 처럼 함수 안에서 같은 이름을 다시 가져오면 전역 patch 가 안 먹는다."""
    module = _load(tmp_path, "local", (
        "from os.path import basename\n\n\n"
        "def shadowed():\n    from os.path import basename\n    return basename('a/b')\n\n\n"
        "def reads_global():\n    return 1\n"
    ))
    try:
        assert "basename" not in cg.runtime_global_reads(module)
        with pytest.raises(AssertionError, match="vacuous patch"):
            cg.patch_targets("basename", [module])
    finally:
        sys.modules.pop(module.__name__, None)


def test_default_arguments_and_decorators_are_not_runtime_reads(tmp_path):
    module = _load(tmp_path, "defaults", (
        "PATTERN = 1\n\n\n"
        "def keeps_a_copy(value=PATTERN):\n    return value\n"
    ))
    try:
        assert "PATTERN" not in cg.runtime_global_reads(module)
    finally:
        sys.modules.pop(module.__name__, None)


def test_sources_keep_function_blocks_from_bleeding_into_the_next_file(tmp_path):
    first = _load(tmp_path, "one", "def _claw_general_one():\n    return 'b66'\n")
    second = _load(tmp_path, "two", '"""module two header mentions b14_client."""\n\n\ndef _claw_general_two():\n    return 2\n')
    try:
        text = cg.sources([first, second])
        block_start = text.index("def _claw_general_one(")
        candidates = [i for i in (text.find("\nasync def ", block_start), text.find("\ndef ", block_start + 1)) if i != -1]
        block = text[block_start:min(candidates)]
        assert "b66" in block and "b14_client" not in block
        assert "_claw_general_" not in cg.MODULE_BOUNDARY, "the boundary must not look like a helper"
    finally:
        for module in (first, second):
            sys.modules.pop(module.__name__, None)


def test_find_attr_requires_exactly_one_defining_module(split_pair):
    leaf, entry = split_pair
    assert cg.find_attr("helper", [leaf, entry]) is leaf.helper
    with pytest.raises(AssertionError, match="exactly one"):
        cg.find_attr("missing", [leaf, entry])


def test_the_scanner_recognises_every_direct_patch_form():
    import ast

    source = "\n".join([
        "import importlib",
        "from app import claw_general_routes as g",
        "import app.claw_general_quota as q",
        "mod = importlib.import_module('app.claw_general_intake')",
        "def t(monkeypatch):",
        "    monkeypatch.setattr(g, 'x', 1)",
        "    monkeypatch.setattr(q, 'x', 1)",
        "    monkeypatch.setattr(mod, 'x', 1)",
        "    monkeypatch.setattr('app.claw_general_context.x', 1)",
        "    patch('app.claw_general_search.x')",
        "    patch.object(g, 'x')",
        "    monkeypatch.setattr(other, 'x', 1)",
        "    monkeypatch.setattr('app.claw_general_run_history.x', 1)",
        "    patch_bound(monkeypatch, 'x', 1)",
    ])
    tree = ast.parse(source)
    lines = [lineno for lineno, _ in cg.direct_patches(tree)]
    assert lines == [6, 7, 8, 9, 10, 11]
    assert cg.helper_patch_names(tree) == [(14, "x")]
