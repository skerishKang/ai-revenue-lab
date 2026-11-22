"""#8054 — 구조 수치 래칫: PR head 실측 ≤ base(main) 실측.

기준선 JSON을 커밋하지 않는다. 매 실행마다 base 트리를 임시 체크아웃하고
head와 **같은 감사 도구 코드**로 둘 다 잰 뒤, 어떤 수치도 base보다 크면 실패한다.

- 늘어나면 실패한다(느슨해지지 않음). 덮지 말고 이기고 있는 규칙을 고치거나
  새 기능을 새 모듈에 둔다.
- 줄어들어도 이제 실패가 아니다. 기준선 갱신 커밋이 필요 없어서, 수치를 줄이는
  PR 두 개가 같은 파일에서 충돌하지 않는다.
- `index_script_tags`는 새 모듈 1개 = script 태그 +1이 정상이라 비교에서 뺀다
  (CTO 결정, #7816).
- 파일 줄 상한 같은 **절대 상한**은 여기서 다루지 않는다.
  `test_r5_file_size_guard_7216.py`·`test_r6_history_file_size_guard_7790.py`가
  계속 소유한다.

base 트리 선택 순서:

1. ``PADIEM_STRUCTURE_BASE_ROOT`` — 이미 준비된 체크아웃 디렉터리.
2. ``PADIEM_STRUCTURE_BASE_SHA`` — PR base 커밋(CI). 없으면 ``git fetch --depth=1``.
3. ``PADIEM_STRUCTURE_BASE_REF`` 또는 ``origin/main`` — 로컬 기본값.
   checkout 이 ``fetch-depth: 1`` 인 브랜치 dispatch·schedule 에는 ``origin/main``
   이 없다. 그때는 ``git fetch --no-tags --depth=1 origin main`` 으로 받아
   ``FETCH_HEAD`` 로 비교한다(#8058 후속). 받지 못하면 skip 하지 않고 실패한다 —
   비교를 건너뛰면 래칫이 조용히 사라진다.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_MODULE = sys.modules[__name__]

TESTS_DIR = Path(__file__).resolve().parent
CHAT_DIR = TESTS_DIR.parent
ROOT = CHAT_DIR.parent.parent
BASELINE_PATH = TESTS_DIR / "structure_baseline.json"
TOOL_PATH = ROOT / "tools" / "chat_structure_audit.py"
STATIC_DIR = CHAT_DIR / "static"

#: CTO 결정(#7816): 새 모듈 = script 태그 +1 이 정상이라 이 키만 비교에서 뺀다.
#: 규칙 수·시트 수 합계도 새 모듈을 허용한다. 대신 시트별 규칙 수를 비교해
#: 기존 시트에 규칙이 늘면 실패한다. !important·색 리터럴은 새 시트에서도 센다.
EXCLUDED_KEYS = {
    "index_script_tags", "css_files", "css_rules", "css_themed_rules",
}
#: 목록은 가드 대상이 아니다. 개수(py_functions_over_300)만 본다.
LIST_KEY = "py_functions_over_300_names"

GROW_GUIDE = (
    "구조 수치가 base(main)보다 늘었다. 되돌린다: 덮지 말고 이기고 있는 규칙을 고친다 / "
    "새 기능은 새 모듈에(!important·새 덮어쓰기 시트·app.js 선언·"
    "D1HistoryStore 메서드 추가 금지 — #7809 기능·수리 PR 규칙)."
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("chat_structure_audit", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flat_metrics(root: Path | None) -> dict[str, int]:
    tool = _load_tool()
    css, _rules = tool.css_metrics(root=root)
    metrics = {
        **css, **tool.js_metrics(root=root), **tool.server_metrics(root=root),
        **tool.test_import_metrics(root=root), **tool.raw_text_assert_metrics(root=root),
    }
    flat: dict = {}
    for key, value in metrics.items():
        if key in ("css_important_by_file", "css_rules_by_file",
                   "css_themed_rules_by_file"):
            for name, count in value.items():
                flat[f"{key}/{name}"] = count
        elif key == LIST_KEY:
            continue
        else:
            flat[key] = value
    return flat


@functools.lru_cache(maxsize=1)
def _head_metrics() -> dict[str, int]:
    return _flat_metrics(None)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True, text=True, capture_output=True, encoding="utf-8",
    )


def _rev_exists(revision: str) -> bool:
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{revision}^{{commit}}"],
        text=True, capture_output=True,
    )
    return probe.returncode == 0


def _remote_branch_for(ref: str) -> str:
    """``origin/main`` → ``main``. 그 밖의 ref 는 그대로 브랜치 이름으로 쓴다."""
    return ref.split("/", 1)[1] if ref.startswith("origin/") else ref


def _same_commit(first: str, second: str) -> bool:
    """두 리비전이 같은 커밋인지. 못 읽으면 False(원래 경로로 잰다)."""
    try:
        a = _git("rev-parse", first).stdout.strip()
        b = _git("rev-parse", second).stdout.strip()
    except subprocess.CalledProcessError:
        return False
    return bool(a) and a == b


def _base_revision() -> str:
    sha = os.environ.get("PADIEM_STRUCTURE_BASE_SHA", "").strip()
    if sha:
        if not _rev_exists(sha):
            _git("fetch", "--no-tags", "--depth=1", "origin", sha)
        return sha
    ref = os.environ.get("PADIEM_STRUCTURE_BASE_REF", "").strip() or "origin/main"
    if _rev_exists(ref):
        return ref
    # 브랜치 dispatch·schedule 의 checkout 은 fetch-depth 1 이라 origin/main 이 없다.
    # 로컬에 없으면 직접 받아서 비교한다(#8058 후속). 받지 못하면 실패한다.
    branch = _remote_branch_for(ref)
    try:
        _git("fetch", "--no-tags", "--depth=1", "origin", branch)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"base 기준({ref})을 준비하지 못했다 — 로컬에 없고 "
            f"`git fetch --no-tags --depth=1 origin {branch}` 가 실패했다: "
            f"{(exc.stderr or '').strip() or 'stderr 없음'}"
        ) from exc
    if not _rev_exists("FETCH_HEAD"):
        raise RuntimeError(
            f"base 기준({ref})을 fetch 했지만 FETCH_HEAD 커밋이 없다"
        )
    return "FETCH_HEAD"


@functools.lru_cache(maxsize=1)
def _base_metrics() -> dict[str, int]:
    provided = os.environ.get("PADIEM_STRUCTURE_BASE_ROOT", "").strip()
    if provided:
        return _flat_metrics(Path(provided))

    revision = _base_revision()
    # #7801: 야간 회귀(main 자체 실행)에서는 base가 HEAD 자체라 같은 트리다.
    # worktree 복제(트리의 전량 체크아웃)와 두 번째 전체 스캔까지 하면
    # 한 시험에 ~수십 초가 들었다. 같은 커밋이면 실측이 동일하므로 head를
    # 재사용한다. 비교 대상이 다를 때는 아래 원래 경로 그대로 잰다.
    if _same_commit(revision, "HEAD"):
        return _head_metrics()
    worktree = Path(tempfile.mkdtemp(prefix="padiem-structure-base-")) / "tree"
    _git("worktree", "add", "--detach", str(worktree), revision)
    try:
        return _flat_metrics(worktree)
    finally:
        subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "remove", "--force", str(worktree)],
            text=True, capture_output=True,
        )
        shutil.rmtree(worktree.parent, ignore_errors=True)


def test_tool_and_head_tree_are_present() -> None:
    assert TOOL_PATH.is_file(), "tools/chat_structure_audit.py 가 없다"
    assert STATIC_DIR.is_dir(), "static 시트 디렉터리가 없다"


def test_no_committed_baseline_file() -> None:
    """#8054: 기준선 파일을 다시 들이지 않는다(base 실측이 유일한 비교 기준)."""
    assert not BASELINE_PATH.exists(), (
        "structure_baseline.json 을 커밋하지 않는다 — base 실측과 비교한다(#8054)."
    )


def _grown_metrics(base: dict, head: dict) -> list[tuple[str, int, int]]:
    """base 키 기준으로 늘어난 지표만. head에 없는 키는 0으로 본다.

    시트를 지우거나 합치면 ``css_important_by_file/<시트>`` 키가 사라진다.
    정상적인 정리이므로 사라진 키는 0(=줄어듦)으로 보고 실패시키지 않는다.
    """
    return [
        (key, base[key], head.get(key, 0))
        for key in base
        if key not in EXCLUDED_KEYS and head.get(key, 0) > base[key]
    ]


def test_head_metrics_never_exceed_the_base_tree() -> None:
    base = _base_metrics()
    head = _head_metrics()
    grew = _grown_metrics(base, head)
    assert not grew, (
        "base보다 늘어난 구조 수치:\n"
        + "\n".join(f"  {key}: {before} → {after} (+{after - before})" for key, before, after in grew)
        + "\n" + GROW_GUIDE
    )


def test_base_and_head_measurements_are_populated() -> None:
    """비교가 성립하는지 확인한다. base에 없는 새 키는 0으로 비교된다."""
    base = _base_metrics()
    head = _head_metrics()
    assert base, "base 실측이 비었다"
    assert head, "head 실측이 비었다"


def test_branch_dispatch_without_origin_main_fetches_main_and_compares(monkeypatch) -> None:
    """#8058 후속: fetch-depth 1 dispatch 에 origin/main 이 없으면 받아서 비교한다."""
    monkeypatch.delenv("PADIEM_STRUCTURE_BASE_SHA", raising=False)
    monkeypatch.delenv("PADIEM_STRUCTURE_BASE_REF", raising=False)
    monkeypatch.setattr(_MODULE, "_rev_exists", lambda revision: revision == "FETCH_HEAD")
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(_MODULE, "_git", fake_git)

    assert _base_revision() == "FETCH_HEAD"
    assert calls == [("fetch", "--no-tags", "--depth=1", "origin", "main")]


def test_base_revision_fetch_failure_fails_instead_of_skipping(monkeypatch) -> None:
    """받지 못하면 skip 이 아니라 이유를 남긴 실패다 — 래칫이 조용히 사라지지 않는다."""
    monkeypatch.delenv("PADIEM_STRUCTURE_BASE_SHA", raising=False)
    monkeypatch.delenv("PADIEM_STRUCTURE_BASE_REF", raising=False)
    monkeypatch.setattr(_MODULE, "_rev_exists", lambda revision: False)

    def failing_git(*args: str) -> subprocess.CompletedProcess:
        raise subprocess.CalledProcessError(
            128, list(args), "", "fatal: couldn't find remote ref main"
        )

    monkeypatch.setattr(_MODULE, "_git", failing_git)

    with pytest.raises(RuntimeError) as excinfo:
        _base_revision()
    assert "origin/main" in str(excinfo.value)
    assert "couldn't find remote ref main" in str(excinfo.value)


def test_vanished_by_sheet_key_reads_as_zero() -> None:
    """시트 삭제/병합으로 사라진 키는 실패가 아니라 0으로 비교된다."""
    base = {"css_important": 10, "css_important_by_file/old-sheet.css": 3}
    assert _grown_metrics(base, {"css_important": 10}) == []
    assert _grown_metrics(base, {"css_important": 11}) == [("css_important", 10, 11)]


def test_test_import_metrics_counts_only_other_test_modules(tmp_path) -> None:
    """#8061: test_ 파일끼리의 import만 센다(_support 공용 헬퍼는 제외)."""
    tests = tmp_path / "apps" / "padiem-chat" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_a.py").write_text(
        "import test_b\nfrom test_c import helper\n"
        "from _support.session import helper as shared\n",
        encoding="utf-8",
    )
    (tests / "test_b.py").write_text("x = 1\n", encoding="utf-8")
    (tests / "test_c.py").write_text("y = 2\n", encoding="utf-8")
    metrics = _load_tool().test_import_metrics(root=tmp_path)
    assert metrics["test_files_importing_test_files"] == 1
    assert metrics["test_to_test_import_edges"] == 2


def test_raw_text_assert_metrics_excludes_user_phrases(tmp_path) -> None:
    """#8060: 원문 글자 단언만 세고 화면 문구 계약은 제외한다."""
    tests = tmp_path / "apps" / "padiem-chat" / "tests"
    tests.mkdir(parents=True)
    # Build the embedded source at runtime so this audit test is not itself
    # classified as a raw-static reader by the lexical detector.
    css_path = "static" + "/app" + ".css"
    read_call = "." + "read_text" + "()"
    (tests / "test_source.py").write_text(
        "from pathlib import Path\n"
        f"CSS = Path('{css_path}')\n"
        f"css = CSS{read_call}\n"
        "def test_token():\n"
        "    assert '--token: red' in css\n"
        "def test_copy():\n"
        "    assert '로그인이 필요합니다' in css\n",
        encoding="utf-8",
    )
    metrics = _load_tool().raw_text_assert_metrics(root=tmp_path)
    assert metrics["test_files_asserting_raw_static_text"] == 1
    assert metrics["raw_static_text_assertions"] == 1


def test_raw_text_assert_metrics_ignores_non_static_reads(tmp_path) -> None:
    tests = tmp_path / "apps" / "padiem-chat" / "tests"
    tests.mkdir(parents=True)
    read_call = "." + "read_text" + "()"
    (tests / "test_other.py").write_text(
        "from pathlib import Path\n"
        f"data = Path('fixture.json'){read_call}\n"
        "def test_value():\n"
        "    assert 'some-key' in data\n",
        encoding="utf-8",
    )
    metrics = _load_tool().raw_text_assert_metrics(root=tmp_path)
    assert metrics == {
        "test_files_asserting_raw_static_text": 0,
        "raw_static_text_assertions": 0,
    }


def _metric_tree(tmp_path, label, sheets):
    """A minimal checkout with only static sheets filled in."""
    root = tmp_path / label
    chat = root / "apps" / "padiem-chat"
    static = chat / "static"
    app_dir = chat / "app"
    tests = chat / "tests"
    for directory in (static, app_dir, tests):
        directory.mkdir(parents=True, exist_ok=True)
    (static / "app.js").write_text("", encoding="utf-8")
    (static / "index.html").write_text("", encoding="utf-8")
    (app_dir / "history.py").write_text("", encoding="utf-8")
    for name, text in sheets.items():
        (static / name).write_text(text, encoding="utf-8")
    return root


def test_new_sheet_rules_do_not_grow_the_ratchet(tmp_path) -> None:
    base = _flat_metrics(_metric_tree(tmp_path, "base", {"base.css": ".a{color:red}"}))
    new_sheet = "".join(".n%d{color:red}" % index for index in range(19))
    head = _flat_metrics(_metric_tree(
        tmp_path, "head", {"base.css": ".a{color:red}", "new.css": new_sheet}))
    assert head["css_rules"] == base["css_rules"] + 19
    assert _grown_metrics(base, head) == []


def test_existing_sheet_rules_still_fail_the_ratchet(tmp_path) -> None:
    base = _flat_metrics(_metric_tree(tmp_path, "base", {"base.css": ".a{color:red}"}))
    head = _flat_metrics(_metric_tree(
        tmp_path, "head", {"base.css": ".a{color:red}.b{color:red}"}))
    grew = _grown_metrics(base, head)
    assert any(key == "css_rules_by_file/base.css" for key, _, _ in grew)


def test_new_sheet_important_still_fails_the_ratchet(tmp_path) -> None:
    base = _flat_metrics(_metric_tree(tmp_path, "base", {"base.css": ".a{color:red}"}))
    head = _flat_metrics(_metric_tree(
        tmp_path, "head", {"base.css": ".a{color:red}",
                           "new.css": ".important{color:red!important}"}))
    grew = _grown_metrics(base, head)
    assert any(key == "css_important" for key, _, _ in grew)
