#!/usr/bin/env python3
"""#7810 [리팩터링 v2 · T0] 채팅 구조 수치 감사 도구.

저장소 파일만 읽어 리팩터링 v2(#7809) 가드 수치를 재고, JSON(--json)이나
사람용 표(--table)로 출력한다. 제품 코드는 읽기만 하고 바꾸지 않는다.

수치 정의(이슈 #7810 표와 동일):
- CSS 대상은 ``apps/padiem-chat/static/*.css``. 주석을 제거한 뒤 세고,
  ``@media``·``@supports`` 안쪽 규칙도 포함한다.
  - ``css_rules``: 선택자 규칙 블록 수(중첩 포함, 전위가 ``@`` 로 시작하는
    블록(@media·@keyframes 프레임 등)은 규칙으로 세지 않는다).
  - ``css_important``: ``!important`` 가 붙은 선언 수.
  - ``css_themed_rules``: 선택자에 ``data-theme`` 이 있는 규칙 수.
  - ``css_color_literals``: 값에 색 숫자(#hex·rgb·rgba·hsl·hsla)가 든 선언 수.
    ``--이름:`` 사용자 속성 정의는 세지 않는다.
  - ``css_local_imports``: 같은 폴더 시트를 부르는 ``@import`` 수(외부 글꼴 제외).
- JS 대상은 ``static/app.js`` 와 ``static/index.html``.
- 서버 대상은 ``apps/padiem-chat/app/*.py``. 함수 줄 수는 ``ast`` 로 잰다.

찾기 옵션(T1 이 사용):
- ``--file <시트> --list colors|important|themed``
- ``--overrides "<선택자>" <속성>`` — 로드 순서(index.html <link> 순서,
  로컬 @import 펼침)대로 나열.

사용:
  python tools/chat_structure_audit.py --json
  python tools/chat_structure_audit.py --table
  python tools/chat_structure_audit.py --file padiem-themes.css --list colors
  python tools/chat_structure_audit.py --overrides ".library-item-title" display
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "apps/padiem-chat/static"
APP_DIR = ROOT / "apps/padiem-chat/app"
APPJS = STATIC / "app.js"
INDEX = STATIC / "index.html"


def project_paths(root: Path | None = None) -> dict[str, Path]:
    """#8054: 측정 대상 트리. 기본은 이 저장소, 인자로 다른 체크아웃(base)을 잰다.

    래칫이 PR head와 base(main)를 같은 도구 코드로 재야 하므로 경로를 인자로
    받는다. 지표 정의(주석 제거·규칙/색/!important 세는 법)는 한 곳에만 있다.
    """
    base = Path(root).resolve() if root is not None else ROOT
    static = base / "apps" / "padiem-chat" / "static"
    return {
        "root": base,
        "static": static,
        "app_dir": base / "apps" / "padiem-chat" / "app",
        "tests_dir": base / "apps" / "padiem-chat" / "tests",
        "appjs": static / "app.js",
        "index": static / "index.html",
    }

COLOR_RX = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I
)
THEME_RX = re.compile(r"data-theme")
LOCAL_IMPORT_RX = re.compile(
    r"@import\s+(?:url\(\s*)?['\"]?([^'\")\s]+\.css)['\"]?\s*\)?", re.I
)


# ---------------------------------------------------------------- tokenizing


def strip_css_comments(text: str) -> str:
    """주석을 공백으로 치환한다. 줄 계산을 위해 개행은 그대로 남긴다."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n - 2 if j == -1 else j
            out.append("".join(c if c == "\n" else " " for c in text[i:j + 2]))
            i = j + 2
        elif ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch:
                if text[j] == "\\":
                    j += 1
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def semicolon_before_block(chunk: str, start: int, end: int) -> int | None:
    """Find a statement terminator before the next block, ignoring strings and functions."""
    quote: str | None = None
    parens = 0
    i = start
    while i < end:
        char = chunk[i]
        if char == "\\":
            i += 2
            continue
        if quote:
            if char == quote:
                quote = None
            i += 1
            continue
        if char in "\"'":
            quote = char
        elif char == "(":
            parens += 1
        elif char == ")" and parens:
            parens -= 1
        elif char == ";" and parens == 0:
            return i
        i += 1
    return None


class Decl:
    """한 선언(prop: value)."""

    __slots__ = ("prop", "value", "line", "selector", "themed", "important")

    def __init__(self, prop: str, value: str, line: int, selector: str, themed: bool):
        self.prop = prop
        self.value = value
        self.line = line
        self.selector = selector
        self.themed = themed
        self.important = "!important" in value


class Rule:
    """하나의 선택자 규칙(선언 목록 포함)."""

    __slots__ = ("selector", "line", "decls", "themed")

    def __init__(self, selector: str, line: int, themed: bool):
        self.selector = selector
        self.line = line
        self.decls: list[Decl] = []
        self.themed = themed


def parse_declarations(body: str, start_line: int, rule: Rule) -> None:
    """규칙 본문(중괄호 없는 내부)을 선언으로 나눠 rule.decls 에 넣는다."""
    depth = 0
    chunk_start = 0
    i, n = 0, len(body)
    parts: list[tuple[int, str]] = []
    while i < n:
        ch = body[i]
        if ch in "\"'":
            j = i + 1
            while j < n and body[j] != ch:
                if body[j] == "\\":
                    j += 1
                j += 1
            i = j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:
            parts.append((chunk_start, body[chunk_start:i]))
            chunk_start = i + 1
        i += 1
    parts.append((chunk_start, body[chunk_start:]))
    for offset, part in parts:
        stripped = part.strip()
        if not stripped or ":" not in stripped:
            continue
        prop, _, value = stripped.partition(":")
        prop = prop.strip()
        value = value.strip()
        if not prop or not value:
            continue
        line = start_line + body.count("\n", 0, offset) + (
            1 if "\n" in body[:offset] else 0
        )
        line = start_line + body.count("\n", 0, offset)
        rule.decls.append(Decl(prop, value, line, rule.selector, rule.themed))


def parse_css(text: str) -> list[Rule]:
    """주석 제거본을 읽어 모든 선택자 규칙(중첩 포함)을 순서대로 돌려준다.

    @media·@supports 등 블록 at-규칙은 안쪽으로 내려가고, @keyframes 프레임
    (전위가 @ 로 시작하지 않는 프레임)은 규칙으로 세지 않기 위해 안쪽 본문의
    선언만 수집한다(프레임 선택자는 테마·재정의 대상이 아니다).
    """
    src = strip_css_comments(text)

    def walk(chunk: str, base_line: int, themed: bool, in_keyframes: bool) -> list[Rule]:
        rules: list[Rule] = []
        i, n = 0, len(chunk)
        while i < n:
            brace = chunk.find("{", i)
            statement_end = semicolon_before_block(
                chunk, i, brace if brace != -1 else n
            )
            if (
                statement_end is not None
                and chunk[i:statement_end].lstrip().startswith("@")
            ):
                # Semicolon at-rules such as @import have no block. Skip the
                # statement before parsing the first following selector block.
                i = statement_end + 1
                continue
            if brace == -1:
                break
            prelude = chunk[i:brace].strip()
            # 본문 끝(짝이 맞는 중괄호) 찾기 — 문자열은 건너뛴다.
            depth = 1
            j = brace + 1
            while j < n and depth:
                c = chunk[j]
                if c in "\"'":
                    k = j + 1
                    while k < n and chunk[k] != c:
                        if chunk[k] == "\\":
                            k += 1
                        k += 1
                    j = k + 1
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                j += 1
            body = chunk[brace + 1:j - 1] if depth == 0 else chunk[brace + 1:j]
            rule_line = base_line + line_of(chunk, i) - 1
            is_at = prelude.startswith("@")
            nested_at = is_at and re.match(r"@([\w-]+)", prelude).group(1) not in {
                "media", "supports", "layer", "container", "scope",
            }
            if is_at:
                # 블록 at-규칙: 안쪽을 다시 연다(@keyframes 프레임 표시).
                name = re.match(r"@([\w-]+)", prelude).group(1)
                child_keyframes = name == "keyframes"
                if not nested_at:
                    rules.extend(walk(body, rule_line, themed, child_keyframes))
            elif not in_keyframes:
                rule = Rule(prelude, rule_line, themed or bool(THEME_RX.search(prelude)))
                parse_declarations(body, rule_line, rule)
                rules.append(rule)
            i = j
        return rules

    return walk(src, 1, False, False)


def sheet_paths(root: Path | None = None) -> list[Path]:
    return sorted(project_paths(root)["static"].glob("*.css"))


# ---------------------------------------------------------------- load order


def load_order(root: Path | None = None) -> list[Path]:
    """index.html <link> 순서 + 각 시트의 로컬 @import 펼침.

    CSS 규칙상 @import 는 시트 앞부분에서 자기보다 앞에 온다. 그래서 시트를
    만날 때마다 그 안의 로컬 @import 를 먼저 펼쳐 넣고 시트 본체를 뒤에 넣는다.
    같은 시트가 여러 번 로드되면 처음 한 번만 넣는다(재정의 분석 기준은
    첫 등장 순서).
    """
    ordered: list[Path] = []
    seen: set[Path] = set()

    def expand(sheet: Path) -> None:
        if sheet in seen or not sheet.exists():
            return
        seen.add(sheet)
        text = strip_css_comments(sheet.read_text(encoding="utf-8", errors="replace"))
        for match in LOCAL_IMPORT_RX.finditer(text):
            target = (sheet.parent / match.group(1)).resolve()
            if target.exists() and target.suffix == ".css":
                expand(target)
        ordered.append(sheet)

    paths = project_paths(root)
    index_src = paths["index"].read_text(encoding="utf-8", errors="replace")
    for href in re.findall(r'<link[^>]+href="([^"]+\.css)"', index_src):
        expand((paths["static"] / href.lstrip("/")).resolve())
    # index.html 에 link 가 없지만 저장소에 있는 시트도 뒤에 붙인다(감사 누락 방지).
    for sheet in sheet_paths(root):
        if sheet not in seen:
            expand(sheet)
    return ordered


# ---------------------------------------------------------------- CSS counts


def css_metrics(root: Path | None = None) -> dict:
    all_rules: dict[Path, list[Rule]] = {}
    files = sheet_paths(root)
    important_by_file: dict[str, int] = {}
    local_imports = 0
    for sheet in files:
        raw = sheet.read_text(encoding="utf-8", errors="replace")
        src = strip_css_comments(raw)
        local_imports += sum(
            1
            for match in LOCAL_IMPORT_RX.finditer(src)
            if (sheet.parent / match.group(1)).resolve().exists()
        )
        rules = parse_css(raw)
        all_rules[sheet] = rules
        important_by_file[sheet.name] = sum(1 for r in rules for d in r.decls if d.important)

    rules_all = [r for rs in all_rules.values() for r in rs]
    decls_all = [d for r in rules_all for d in r.decls]
    color_decls = [
        d for d in decls_all if not d.prop.startswith("--") and COLOR_RX.search(d.value)
    ]
    return {
        "css_files": len(files),
        "css_rules": len(rules_all),
        "css_important": sum(important_by_file.values()),
        "css_important_by_file": important_by_file,
        "css_themed_rules": sum(1 for r in rules_all if r.themed),
        "css_themed_important": sum(1 for d in decls_all if d.important and d.themed),
        "css_color_literals": len(color_decls),
        "css_color_literals_unthemed": sum(1 for d in color_decls if not d.themed),
        "css_local_imports": local_imports,
    }, all_rules


# ---------------------------------------------------------------- JS counts


FORWARDER_RX = re.compile(
    r"function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{([^{}]*)\}", re.S
)
# 전달 함수 본문: 어느모듈Module().이름(...) 또는 즉시 생성한 모듈인스턴스.이름(...)
# (R5 B2: lazy 팩토리 대신 원래 자리에서 만든 인스턴스를 부르는 형태도 같은 전달 함수다).
FORWARDER_BODY_RX = re.compile(
    r"^(?:return\s+)?([A-Za-z_$][\w$]*)(?:\(\))?\.([A-Za-z_$][\w$]*)\([^;]*\);?$",
    re.S,
)
MODULE_CREATE_RX = re.compile(
    r"(?:window\.)?PadiemChat[\w]*Module\.create\s*\(", re.S
)


def strip_js_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n - 2 if j == -1 else j
            out.append("".join(c if c == "\n" else " " for c in text[i:j + 2]))
            i = j + 2
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
        elif text[i] in "\"'`":
            q = text[i]
            j = i + 1
            while j < n and text[j] != q:
                if text[j] == "\\":
                    j += 1
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def top_level_entries(object_body: str) -> int:
    """객체 리터럴 본문의 최상위 항목 수(중괄호·괄호·문자열 인식)."""
    depth_sq = depth_par = 0
    entries = 1
    in_str = ""
    i, n = 0, len(object_body)
    while i < n:
        ch = object_body[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = ""
            i += 1
            continue
        if ch in "\"'`":
            in_str = ch
        elif ch in "{[":
            depth_sq += 1
        elif ch in "}]":
            depth_sq -= 1
        elif ch == "(":
            depth_par += 1
        elif ch == ")":
            depth_par -= 1
        elif ch == "," and depth_sq == 0 and depth_par == 0:
            entries += 1
        i += 1
    # 마지막 실질 항목 뒤의 트레일링 콤마 보정
    tail = object_body.rstrip()
    if tail.endswith(","):
        return max(1, entries - 1)
    return entries


def js_metrics(root: Path | None = None) -> dict:
    paths = project_paths(root)
    src = paths["appjs"].read_text(encoding="utf-8", errors="replace")
    clean = strip_js_comments(src)
    forwarders = 0
    for match in FORWARDER_RX.finditer(clean):
        if FORWARDER_BODY_RX.match(match.group(3).strip()):
            forwarders += 1
    deps_total = 0
    for match in MODULE_CREATE_RX.finditer(clean):
        open_paren = clean.index("(", match.start())
        depth = 1
        j = open_paren + 1
        while j < len(clean) and depth:
            c = clean[j]
            if c in "\"'`":
                q = c
                j += 1
                while j < len(clean) and clean[j] != q:
                    if clean[j] == "\\":
                        j += 1
                    j += 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        inner = clean[open_paren + 1:j - 1]
        if "PadiemChatAppContext" in clean[max(0, match.start() - 60):match.end() + 5]:
            continue  # 공유 문맥 묶음은 제외
        brace = inner.find("{")
        if brace == -1:
            continue
        depth_b = 1
        k = brace + 1
        while k < len(inner) and depth_b:
            c = inner[k]
            if c in "\"'`":
                q = c
                k += 1
                while k < len(inner) and inner[k] != q:
                    if inner[k] == "\\":
                        k += 1
                    k += 1
            elif c == "{":
                depth_b += 1
            elif c == "}":
                depth_b -= 1
            k += 1
        deps_total += top_level_entries(inner[brace + 1:k - 1])
    index_src = paths["index"].read_text(encoding="utf-8", errors="replace")
    return {
        "appjs_lines": src.count("\n") + (0 if src.endswith("\n") else 1),
        "appjs_forwarders": forwarders,
        "appjs_deps_total": deps_total,
        "appjs_function_decls": len(re.findall(r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(", clean)),
        # DOM 조회: getElementById 와 querySelector 식별자 등장 수.
        # querySelector 는 식별자 앞부분 일치로 세어 querySelectorAll 도 포함한다
        # (이슈 #7810 표 값 212 = 187 + 25 과 같은 정의).
        "appjs_dom_lookups": len(re.findall(r"\bgetElementById\b|\bquerySelector", clean)),
        "appjs_listeners": len(re.findall(r"\baddEventListener\s*\(", clean)),
        "index_script_tags": len(re.findall(r"<script", index_src, re.I)),
    }


# ---------------------------------------------------------------- server counts


def iter_app_py(root: Path | None = None) -> list[Path]:
    return sorted(project_paths(root)["app_dir"].glob("*.py"))


def class_span(src_lines: list[str], name: str) -> tuple[int, int] | None:
    """클래스 본문의 (시작 줄, 끝 줄). 1-based. 끝은 다음 최상위 문장 전 줄."""
    for idx, line in enumerate(src_lines):
        if line.startswith(f"class {name}") and line.rstrip().endswith(":"):
            start = idx + 1
            end = len(src_lines)
            for j in range(idx + 1, len(src_lines)):
                stripped = src_lines[j].strip()
                if stripped and not src_lines[j].startswith((" ", "\t", ")", "@")):
                    end = j  # 다음 최상위 문장 직전 줄까지가 클래스 몸통
                    break
            return start, end
    return None


def server_metrics(root: Path | None = None) -> dict:
    app_dir = project_paths(root)["app_dir"]
    history = app_dir / "history.py"
    hist_lines = history.read_text(encoding="utf-8", errors="replace").splitlines()
    span = class_span(hist_lines, "D1HistoryStore")
    d1_lines = span[1] - span[0] + 1 if span else 0
    d1_methods = 0
    if span:
        d1_methods = sum(
            1
            for line in hist_lines[span[0]:span[1]]
            if re.match(r"    (?:async )?def\s+\w+", line)
        )
    over_300: list[tuple[str, str, int]] = []
    for path in iter_app_py(root):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = max(
                    getattr(node, "end_lineno", node.lineno),
                    *(n.end_lineno for n in ast.walk(node) if hasattr(n, "end_lineno")),
                )
                length = end - node.lineno + 1
                if length >= 300:
                    over_300.append((path.name, node.name, length))
    over_300.sort(key=lambda item: -item[2])
    return {
        "history_py_lines": len(hist_lines),
        "d1_history_store_lines": d1_lines,
        "d1_history_store_methods": d1_methods,
        "py_functions_over_300": len(over_300),
        "py_functions_over_300_names": over_300,
    }


# ---------------------------------------------------------------- test imports


def test_import_metrics(root: Path | None = None) -> dict:
    """#8061: test_ 파일이 다른 test_ 파일을 import하는 횟수.

    공용 헬퍼가 시험 파일에 남아 있으면 시험끼리 얽혀 옮기기 어렵다. AST로
    모듈 이름만 세고 값·경로·본문은 남기지 않는다. 공용 헬퍼는
    ``tests/_support/`` 에 두는 것이 규칙이므로 그 import는 여기에 잡히지 않는다.
    """
    files = 0
    edges = 0
    for path in sorted(project_paths(root)["tests_dir"].glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        local = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[0].startswith("test_"):
                    local += 1
            elif isinstance(node, ast.Import):
                local += sum(
                    1 for alias in node.names
                    if alias.name.split(".")[0].startswith("test_")
                )
        if local:
            files += 1
            edges += local
    return {
        "test_files_importing_test_files": files,
        "test_to_test_import_edges": edges,
    }


# ---------------------------------------------------------------- find options


def list_declarations(sheet_name: str, kind: str, root: Path | None = None) -> list[str]:
    static = project_paths(root)["static"]
    sheet = (static / sheet_name).resolve()
    if not sheet.exists():
        sheet = static / sheet_name
    if not sheet.exists():
        raise SystemExit(f"시트를 찾을 수 없습니다: {sheet_name}")
    rules = parse_css(sheet.read_text(encoding="utf-8", errors="replace"))
    rows: list[str] = []
    for rule in rules:
        for decl in rule.decls:
            hit = (
                kind == "important" and decl.important
                or kind == "colors" and not decl.prop.startswith("--") and COLOR_RX.search(decl.value)
                or kind == "themed" and rule.themed
            )
            if hit:
                rows.append(f"{decl.line} · {rule.selector} · {decl.prop} · {decl.value}")
    return rows


def overrides_search(selector: str, prop: str, root: Path | None = None) -> list[str]:
    """마지막 복합 선택자가 같고 속성이 같은 규칙을 로드 순서대로 나열한다."""
    wanted = " ".join(selector.split()).lower()
    rows: list[str] = []
    for sheet in load_order(root):
        rules = parse_css(sheet.read_text(encoding="utf-8", errors="replace"))
        for rule in rules:
            for part in rule.selector.split(","):
                compounds = re.split(r"[>\s~+]+", part.strip())
                last = " ".join(compounds[-1].split()).lower() if compounds else ""
                if last != wanted:
                    continue
                for decl in rule.decls:
                    if decl.prop.lower() == prop.lower():
                        marks = []
                        if decl.important:
                            marks.append("!important")
                        if decl.themed:
                            marks.append("테마")
                        rows.append(
                            f"{sheet.name}:{decl.line} · {rule.selector} · "
                            f"{decl.prop}: {decl.value}"
                            + (f" [{', '.join(marks)}]" if marks else "")
                        )
    return rows


# ---------------------------------------------------------------- output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    parser.add_argument("--table", action="store_true", help="사람용 표로 출력")
    parser.add_argument("--file", metavar="시트", help="시트 이름(예: padiem-themes.css)")
    parser.add_argument("--list", dest="kind", choices=["colors", "important", "themed"], help="나열 종류")
    parser.add_argument("--overrides", nargs=2, metavar=("선택자", "속성"), help="재정의 사슬 나열")
    parser.add_argument("--root", metavar="트리", help="측정 대상 체크아웃(기본: 이 저장소). 래칫의 base 실측용")
    args = parser.parse_args()
    root = Path(args.root) if args.root else None

    if args.overrides:
        rows = overrides_search(args.overrides[0], args.overrides[1], root)
        print("\n".join(rows) if rows else "(해당 규칙 없음)")
        return
    if args.file and args.kind:
        rows = list_declarations(args.file, args.kind, root)
        print("\n".join(rows) if rows else "(해당 선언 없음)")
        return

    css, _rules = css_metrics(root)
    metrics: dict = {
        **css, **js_metrics(root), **server_metrics(root), **test_import_metrics(root),
    }

    if args.json or not args.table:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return
    width = max(len(k) for k in metrics if k != "css_important_by_file" and k != "py_functions_over_300_names")
    for key, value in metrics.items():
        if key == "css_important_by_file":
            for name, count in sorted(value.items(), key=lambda kv: -kv[1]):
                if count:
                    print(f"  {name:<{width}} {count:>6}")
        elif key == "py_functions_over_300_names":
            for name, fn, length in value:
                print(f"  {name}:{fn} {length}줄")
        else:
            print(f"{key:<{width}} {value:>8}")


if __name__ == "__main__":
    main()
