#!/usr/bin/env python3
"""R5 0단계-B — app.js 개요 추출기 (#7216).

app.js 를 읽어 최상위 함수/변수와 줄 범위, 함수 간 호출, window 전역 노출,
DOM id, addEventListener 대상을 추출하고 기능 구역별 집계를 JSON 으로 출력한다.
코드 이동 없음. 이 출력만이 모듈 지도 문서의 근거가 된다.

2026-11-09 보완: 구역별 함수·변수 줄 합과 전체 줄 수의 차이(약 1,700줄)를
설명하기 위해 함수 밖 최상위 코드 블록(이벤트 연결·초기화·즉시 실행)과
주석/빈 줄을 따로 세어 line_accounting 으로 출력한다.

사용: python tools/r5_appjs_map.py [app.js 경로]
      python tools/r5_appjs_map.py --modules

--modules (R5 2부 T2 B2-0, #7812): 모듈 연결부별 현황표 — (가) 그 모듈만 쓰는
선언(줄 범위), (나) 자기 리스너 블록, (다) deps 항목을 자기 것/공유/모듈 API 로
분류, (라) 모듈 전용 전달 함수. 한 줄 전달 함수를 인식한다(§3.3 0-4, 위험 R-18).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
APP = Path(_ARGS[0]) if _ARGS else ROOT / "apps/padiem-chat/static/app.js"

AREAS = [
    ("로그인 세션", re.compile(r"auth|login|session|account|password|profile|logout", re.I)),
    ("최근 대화 메뉴", re.compile(r"history|recent|rename|pin|deleteConversation|patchConversation", re.I)),
    ("사이드바", re.compile(r"sidebar|sidenav|collapse|navButton|sideNav|projects?Nav|workspaceNav", re.I)),
    ("라이브러리", re.compile(r"library|outputs|savedOutput", re.I)),
    ("캘린더", re.compile(r"calendar|meeting", re.I)),
    ("Claw", re.compile(r"claw|pc[A-Z]|device|mesh|drive|connector|oracle", re.I)),
    ("설정", re.compile(r"settings|theme|admin|model|tier|language", re.I)),
    ("유틸", re.compile(r"util|pdf|xlsx|export|search|quote", re.I)),
    ("대화", re.compile(r"conversation|message|chat|stream|answer|send|composer|attachment|input", re.I)),
]

DOM_AREA_HINTS = [
    ("설정", re.compile(r"settingsDialog|settingsButton|settingsCloseButton|advancedSettingsView|profileToggle")),
    ("사이드바", re.compile(r"sidebarCollapseButton|sidebarRestoreButton|sidebarScrim|mobileMenu|mobileClose")),
    ("캘린더", re.compile(r"calendar|meeting")),
    ("Claw", re.compile(r"claw|pc[A-Z]|device|mesh|connector|drive")),
    ("로그인 세션", re.compile(r"auth|login|password|account|profile")),
    ("최근 대화 메뉴", re.compile(r"history|recent|rename|pin")),
    ("대화", re.compile(r"messageList|composer|attachment|conversation|stream")),
]


def area_of(name):
    for area, rx in AREAS:
        if rx.search(name):
            return area
    return "공통"


def block_area(text):
    scores = {}
    for area, rx in DOM_AREA_HINTS:
        n = len(rx.findall(text))
        if n:
            scores[area] = scores.get(area, 0) + n * 3
    for area, rx in AREAS:
        n = len(rx.findall(text))
        if n:
            scores[area] = scores.get(area, 0) + n
    if not scores:
        return "공통"
    return max(scores.items(), key=lambda item: item[1])[0]


def block_kind(text):
    if ".addEventListener(" in text:
        return "listener"
    if re.search(r"^\s*(?:if|for|while|try)\b", text, re.M):
        return "control"
    if "=>" in text or "function" in text:
        return "callback"
    if "=" in text:
        return "assignment"
    return "statement"


def _strip_code(line, state=None):
    """한 줄에서 주석(줄·블록)·문자열·템플릿 본문·정규식 리터럴을 걷어낸 코드를
    돌려준다. 블록 주석과 여러 줄 템플릿 상태는 ``state`` 딕셔너리로 줄 사이에
    유지된다. 정규식 리터럴(예: ``/^https:\\/\\//``) 안의 ``//``와 ``{}``는
    깊이 계산을 어긋나게 하므로 함께 걷어낸다."""
    if state is None:
        state = {"comment": False, "template": False}
    out = []
    i, n = 0, len(line)
    while i < n:
        if state["comment"]:
            end = line.find("*/", i)
            if end == -1:
                return "".join(out), state
            i = end + 2
            state["comment"] = False
            continue
        if state["template"]:
            ch = line[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                state["template"] = False
            i += 1
            continue
        ch = line[i]
        if ch == "/" and line[i + 1: i + 2] == "/":
            break
        if ch == "/" and line[i + 1: i + 2] == "*":
            state["comment"] = True
            i += 2
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            while i < n:
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "`":
            state["template"] = True
            i += 1
            continue
        if ch == "/":
            # 정규식 리터럴 판정(관용적 규칙): 직전 유효 문자가 값의 끝이 아니면
            # 나눗셈이 아니라 정규식이다.
            prev = "".join(out).rstrip()
            last = prev[-1] if prev else ""
            if last == "" or last in "(,=:[!&|?{};" or prev.endswith("return") or prev.endswith("typeof"):
                i += 1
                in_class = False
                while i < n:
                    c = line[i]
                    if c == "\\":
                        i += 2
                        continue
                    if c == "[":
                        in_class = True
                    elif c == "]":
                        in_class = False
                    elif c == "/" and not in_class:
                        i += 1
                        while i < n and line[i].isalpha():
                            i += 1
                        break
                    i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out), state


def _depth_delta(code):
    return (code.count("(") - code.count(")")
            + code.count("{") - code.count("}")
            + code.count("[") - code.count("]"))


def find_close_top(lines, i):
    """닫는 줄을 찾는다. R-18: (1) 한 줄 선언(한 줄 전달 함수 등)은 자기 줄에서
    닫히고, (2) 닫는 중괄호의 들여쓰기가 어긋나 있어도(예: 6칸) 괄호 깊이가
    0으로 돌아오는 첫 줄에서 함수가 끝난다."""
    depth = 0
    state = {"comment": False, "template": False}
    for j in range(i, len(lines)):
        code, state = _strip_code(lines[j], state)
        depth += _depth_delta(code)
        if depth <= 0:
            return j
    return i


def variable_end(lines, i):
    """Multi-line initializers: consume until bracket depth returns to zero."""
    depth = 0
    state = {"comment": False, "template": False}
    for j in range(i, len(lines)):
        code, state = _strip_code(lines[j], state)
        depth += _depth_delta(code)
        # 한 줄 선언은 그 줄에서 끝난다(세미콜론 확인). 여러 줄 초기화는
        # 괄호 균형이 0으로 돌아오는 줄에서 끝난다.
        if depth <= 0 and (j > i or code.rstrip().endswith(";")):
            return j
    return i


def main():
    lines = APP.read_text(encoding="utf-8").splitlines()
    funcs = []
    variables = []
    var_lines = 0
    i = 0
    fn_start = re.compile(r"^  (?:async )?function (\w+)\s*\(")
    var_start = re.compile(r"^  (?:const|let) (\w+)\s*=")
    while i < len(lines):
        m = fn_start.match(lines[i])
        if m:
            name = m.group(1)
            start = i + 1
            j = find_close_top(lines, i)
            end = j + 1
            funcs.append({"name": name, "start": start, "end": end,
                          "lines": end - start + 1, "area": area_of(name),
                          "body": "\n".join(lines[i:j + 1])})
            i = j + 1
            continue
        v = var_start.match(lines[i])
        if v:
            end = variable_end(lines, i)
            variables.append({"name": v.group(1), "line": i + 1, "area": area_of(v.group(1)),
                              "lines": end - i + 1})
            var_lines += end - i + 1
            i = end + 1
            continue
        i += 1

    consumed = set()
    for f in funcs:
        consumed.update(range(f["start"] - 1, f["end"]))
    for v in variables:
        consumed.update(range(v["line"] - 1, v["line"] - 1 + v["lines"]))

    blank_lines = 0
    comment_lines = 0
    code_indices = []
    in_block_comment = False
    for idx, line in enumerate(lines):
        if idx in consumed:
            continue
        stripped = line.strip()
        if in_block_comment:
            comment_lines += 1
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            comment_lines += 1
            if "*/" not in stripped:
                in_block_comment = True
            continue
        if stripped == "":
            blank_lines += 1
            continue
        if stripped.startswith("//"):
            comment_lines += 1
            continue
        code_indices.append(idx)

    blocks = []
    for idx in code_indices:
        text = lines[idx]
        if blocks and blocks[-1]["end"] == idx:
            blocks[-1]["end"] = idx + 1
            blocks[-1]["lines"] += 1
            blocks[-1]["text"].append(text)
        else:
            blocks.append({"start": idx + 1, "end": idx + 1, "lines": 1, "text": [text]})
    top_level_code = []
    for block in blocks:
        joined = "\n".join(block["text"])
        top_level_code.append({
            "start": block["start"], "end": block["end"], "lines": block["lines"],
            "area": block_area(joined), "kind": block_kind(joined),
            "first": block["text"][0].strip()[:110],
        })
    code_lines = sum(b["lines"] for b in top_level_code)

    area_code = {}
    for block in top_level_code:
        entry = area_code.setdefault(block["area"], {"blocks": 0, "lines": 0})
        entry["blocks"] += 1
        entry["lines"] += block["lines"]

    names = {f["name"] for f in funcs}
    calls = []
    for f in funcs:
        for other in names:
            if other == f["name"]:
                continue
            n = len(re.findall(r"\b" + re.escape(other) + r"\s*\(", f["body"]))
            if n:
                calls.append({"from": f["name"], "to": other, "count": n,
                              "from_area": f["area"],
                              "to_area": next(x["area"] for x in funcs if x["name"] == other)})

    text = "\n".join(lines)
    window_globals = sorted(set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", text)))
    dom_ids = sorted(set(re.findall(r"getElementById\(\s*[\"']([\w-]+)[\"']\s*\)", text))
                     | set(re.findall(r"querySelector\(\s*[\"']#([\w-]+)[\"']", text)))
    listeners = [{"target": t, "event": e} for t, e in
                 re.findall(r"([A-Za-z_$][\w$]*)\??\.addEventListener\(\s*[\"']([\w:-]+)[\"']", text)]

    area_summary = {}
    for f in funcs:
        a = area_summary.setdefault(f["area"], {"functions": 0, "lines": 0})
        a["functions"] += 1
        a["lines"] += f["lines"]
    for v in variables:
        a = area_summary.setdefault(v["area"], {"functions": 0, "lines": 0})
        a["lines"] += v["lines"]
    cross = {}
    for c in calls:
        if c["from_area"] != c["to_area"]:
            key = f"{c['from_area']}->{c['to_area']}"
            cross[key] = cross.get(key, 0) + c["count"]

    out = {
        "total_lines": len(lines),
        "top_level_functions": [{k: f[k] for k in ("name", "start", "end", "lines", "area")} for f in funcs],
        "top_level_variables": [{k: v[k] for k in ("name", "line", "area", "lines")} for v in variables],
        "calls": [{k: c[k] for k in ("from", "to", "count", "from_area", "to_area")} for c in calls],
        "window_globals": window_globals,
        "dom_ids": dom_ids,
        "listeners": listeners,
        "area_summary": area_summary,
        "cross_area_calls": cross,
        "line_accounting": {
            "total_lines": len(lines),
            "function_lines": sum(f["lines"] for f in funcs),
            "variable_lines": var_lines,
            "blank_lines": blank_lines,
            "comment_lines": comment_lines,
            "top_level_code_lines": code_lines,
            "top_level_code_blocks": len(top_level_code),
            "top_level_code_by_area": area_code,
        },
        "top_level_code": top_level_code,
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


# --------------------------------------------------------------------------
# R5 2부(T2) B2-0 — 모듈 연결부별 현황표 추출기 (설계 §3.3 0-4).
#
# tools/r5_appjs_map.py 는 한 줄 전달 함수를 "그냥 함수"로만 읽어(위험 R-18),
# 모듈 연결부별 귀속(자기 선언·자기 리스너·deps 자기/공유·전용 전달 함수)을
# 낼 수 없었다. --modules 모드는 여기를 고친다: 전달 함수(공장 호출 한 줄)를
# 인식하고, 모든 최상위 영역(함수·리스너 등록·선언)을 각 모듈에 귀속시켜
# JSON 으로 낸다. 읽기 전용이며 결정적이다. (가) 자기 선언 (나) 리스너 블록
# (다) deps 자기/공유/모듈API (라) 모듈 전용 전달 함수.

FORWARDER_RX = re.compile(
    r"^  (?:async )?function (?P<name>\w+)\((?P<params>[^)]*)\) "
    r"\{ return (?P<factory>\w+)\(\)\.(?P=name)\((?P<args>[^)]*)\); \}$"
)
CREATE_RX = re.compile(r"(?P<factory>\w+)Instance = window\.PadiemChat(?P<export>\w+)Module\.create\(\{")
LISTENER_RX = re.compile(
    r"^  (?:if \([^)]*\) )?(?:window|document|[\w$]+)\??\.addEventListener\("
)


def _statement_end(lines, start):
    """addEventListener 문장의 닫는 줄(괄호 깊이 0 + 세미콜론/}); 확인)."""
    depth = 0
    state = {"comment": False, "template": False}
    for j in range(start, len(lines)):
        code, state = _strip_code(lines[j], state)
        depth += _depth_delta(code)
        stripped = code.rstrip()
        if depth <= 0 and (stripped.endswith(";") or stripped.endswith("});")):
            return j
    return start


def _region_text(lines, start, end):
    return "\n".join(lines[start:end + 1])


def _code_only(text):
    """영역 텍스트에서 주석을 걷어낸 코드만 돌려준다(식별자 대조용)."""
    out = []
    state = {"comment": False, "template": False}
    for line in text.splitlines():
        code, state = _strip_code(line, state)
        out.append(code)
    return "\n".join(out)


def parse_module_analysis(lines):
    # 1) 모듈 연결부: window.PadiemChat<X>Module.create({ ... }) + deps 항목.
    modules = {}
    for i, line in enumerate(lines):
        m = CREATE_RX.search(line)
        if not m:
            continue
        depth = 0
        state = {"comment": False, "template": False}
        end = i
        for j in range(i, len(lines)):
            code, state = _strip_code(lines[j], state)
            depth += _depth_delta(code)
            if depth <= 0:
                end = j
                break
        deps_block = _region_text(lines, i, end)
        deps = []
        for dm in re.finditer(r"\b(get|set) (\w+)\(", deps_block):
            deps.append({"kind": dm.group(1), "name": dm.group(2)})
        modules[m.group("export")] = {
            "export": m.group("export"),
            "factory": m.group("factory"),
            "create_line": i + 1,
            "create_end": end + 1,
            "deps_block": deps_block,
            "deps": deps,
        }

    # 2) 전달 함수(공장 호출 한 줄) → 모듈 매핑.
    factory_to_module = {v["factory"]: k for k, v in modules.items()}
    forwarders = {}
    for i, line in enumerate(lines):
        fm = FORWARDER_RX.match(line)
        if not fm:
            continue
        target = factory_to_module.get(fm.group("factory"))
        if target:
            forwarders[fm.group("name")] = {
                "name": fm.group("name"),
                "module": target,
                "line": i + 1,
            }

    # 3) 영역: 최상위 함수·리스너 등록·선언·최상위 코드 런.
    regions = []
    fn_start = re.compile(r"^  (?:async )?function (\w+)\s*\(")
    var_start = re.compile(r"^  (?:const|let) (\w+)\s*=")
    consumed = [False] * len(lines)
    i = 0
    while i < len(lines):
        fm = fn_start.match(lines[i])
        if fm:
            end = find_close_top(lines, i)
            regions.append({"kind": "function", "name": fm.group(1),
                            "start": i + 1, "end": end + 1,
                            "text": _region_text(lines, i, end)})
            for k in range(i, end + 1):
                consumed[k] = True
            i = end + 1
            continue
        vm = var_start.match(lines[i])
        if vm:
            end = variable_end(lines, i)
            regions.append({"kind": "decl", "name": vm.group(1),
                            "start": i + 1, "end": end + 1,
                            "text": _region_text(lines, i, end)})
            for k in range(i, end + 1):
                consumed[k] = True
            i = end + 1
            continue
        if LISTENER_RX.match(lines[i]):
            end = _statement_end(lines, i)
            head = lines[i]
            tm = re.search(r'\.addEventListener\(\s*["\']([^"\']+)["\']', head)
            regions.append({"kind": "listener",
                            "target": head.strip().split(".addEventListener")[0].strip(),
                            "event": tm.group(1) if tm else "?",
                            "start": i + 1, "end": end + 1,
                            "text": _region_text(lines, i, end)})
            for k in range(i, end + 1):
                consumed[k] = True
            i = end + 1
            continue
        i += 1
    # 최상위 코드 런: 공백 줄은 런을 끊고 주석 줄은 런에 붙인다.
    i = 0
    while i < len(lines):
        if consumed[i] or not lines[i].strip():
            i += 1
            continue
        j = i
        while j < len(lines):
            if consumed[j]:
                break
            if not lines[j].strip():
                if j + 1 < len(lines) and lines[j + 1].strip() and not consumed[j + 1]:
                    j += 1
                    continue
                break
            j += 1
        end = j - 1
        while end > i and not lines[end].strip():
            end -= 1
        if end >= i:
            regions.append({"kind": "code", "name": None,
                            "start": i + 1, "end": end + 1,
                            "text": _region_text(lines, i, end)})
        i = j

    for reg in regions:
        reg["code"] = _code_only(reg["text"])

    def rkey(reg):
        return (reg["kind"], reg.get("name") or reg.get("event") or reg["start"], reg["start"])

    def regions_referencing(name, skip=None):
        rx = re.compile(r"\b" + re.escape(name) + r"\b")
        out = []
        for reg in regions:
            if skip is not None and rkey(reg) == skip:
                continue
            if rx.search(reg["code"]):
                out.append(reg)
        return out

    # 4) 모듈별 귀속.
    for export, mod in modules.items():
        fwd_names = {n for n, f in forwarders.items() if f["module"] == export}
        mod["forwarders"] = sorted(fwd_names)
        factory_name = mod["factory"]

        # (나) 리스너 귀속: 핸들러가 참조하는 전달 함수가 전부 M 것이면 M.
        own_listeners = []
        for reg in regions:
            if reg["kind"] != "listener":
                continue
            stripped = reg["code"]
            mods = {forwarders[n]["module"] for n in forwarders
                    if re.search(r"\b" + re.escape(n) + r"\b", stripped)}
            if mods == {export}:
                own_listeners.append({"target": reg["target"], "event": reg["event"],
                                      "start": reg["start"], "end": reg["end"]})
        mod["own_listeners"] = own_listeners

        # 코드 런 귀속: M 의 전달 함수/공장을 참조하면 M.
        own_code = []
        for reg in regions:
            if reg["kind"] != "code":
                continue
            stripped = reg["code"]
            refs = {forwarders[n]["module"] for n in forwarders
                    if re.search(r"\b" + re.escape(n) + r"\b", stripped)}
            if re.search(r"\b" + re.escape(factory_name) + r"\b", stripped):
                refs.add(export)
            if refs == {export}:
                own_code.append({"start": reg["start"], "end": reg["end"],
                                 "text": reg["text"]})

        core_keys = {(r["kind"], r.get("name") or r.get("event") or r["start"], r["start"])
                     for r in regions
                     if (r["kind"] == "function" and r["name"] == factory_name)
                     or (r["kind"] == "function" and r["name"] in fwd_names)
                     or (r["kind"] == "listener"
                         and any(l["start"] == r["start"] for l in own_listeners))
                     or (r["kind"] == "code"
                         and any(c["start"] == r["start"] for c in own_code))}

        # (가) 자기 선언: 참조 영역이 전부 M 것(+M 자기 선언 체인)인 최상위 const/let.
        own_decls = []
        reachable = set(core_keys)
        decl_regions = [r for r in regions if r["kind"] == "decl"]
        changed = True
        while changed:
            changed = False
            for reg in decl_regions:
                key = rkey(reg)
                if key in reachable:
                    continue
                refs = regions_referencing(reg["name"], skip=key)
                keys = {rkey(r) for r in refs}
                if not keys:
                    # 참조가 없으면 그 이름을 deps 로 받는 모듈이 하나면 그 모듈 것.
                    owners = {k for k, v in modules.items()
                              if any(d["name"] == reg["name"] for d in v["deps"])}
                    if owners == {export}:
                        reachable.add(key)
                        changed = True
                    continue
                if keys <= reachable:
                    reachable.add(key)
                    changed = True
        for reg in decl_regions:
            key = rkey(reg)
            if key in reachable and key not in core_keys:
                # 공장 인스턴스 let(…ModuleInstance)은 배포 접착이라 B7 소관 — B2 목록에서 뺀다.
                if reg["name"].endswith("ModuleInstance"):
                    continue
                # app.provide(...) 신형 모듈 인스턴스도 B7(등록부) 소관 — B2 목록에서 뺀다.
                if "app.provide(" in _code_only(reg["text"]):
                    continue
                # app.provide(...) 신형 모듈 인스턴스도 B7(등록부) 소관 — B2 목록에서 뺀다.
                if "app.provide(" in _code_only(reg["text"]):
                    continue
                own_decls.append({"name": reg["name"], "start": reg["start"], "end": reg["end"]})
        mod["own_declarations"] = own_decls

        # (다) deps 분류: 참조 영역이 전부 M 것(+M 자기 선언)이면 자기 것.
        # 같은 모듈의 전달 함수 이름은 선언 이동으로 없어지지 않는다(내부 호출용 —
        # 등록부 B7 에서 없어진다) so module_api 로 간다.
        own_deps, shared_deps, module_api_deps = [], [], []
        for dep in mod["deps"]:
            name = dep["name"]
            if name in fwd_names:
                module_api_deps.append(name)
                continue
            keys = {rkey(r) for r in regions_referencing(name)}
            if keys and keys <= reachable:
                own_deps.append(name)
            else:
                decl = any(r["kind"] == "decl" and r["name"] == name for r in regions)
                (shared_deps if decl else module_api_deps).append(name)
        mod["deps_own"] = sorted(set(own_deps))
        mod["deps_shared"] = sorted(set(shared_deps))
        mod["deps_module_api"] = sorted(set(module_api_deps))

        # (라) 모듈 전용 전달 함수: 참조가 전부 M 의 리스너/코드 안.
        own_fwd, shared_fwd = [], []
        for name in sorted(fwd_names):
            refs = regions_referencing(name)
            keys = {rkey(r) for r in refs}
            if keys and keys <= core_keys and all(
                    r["kind"] in ("listener", "code") for r in refs):
                own_fwd.append(name)
            else:
                shared_fwd.append(name)
        mod["module_only_forwarders"] = own_fwd
        mod["shared_forwarders"] = shared_fwd

        # 투영(B2 에서 app.js 에서 없어지는 줄).
        decl_lines = sum(d["end"] - d["start"] + 1 for d in own_decls)
        listener_lines = sum(l["end"] - l["start"] + 1 for l in own_listeners)
        dep_lines = sum(1 for _ in mod["deps_own"])
        fwd_lines = len(own_fwd)
        mod["projection"] = {
            "decl_lines": decl_lines,
            "listener_lines": listener_lines,
            "own_deps": dep_lines,
            "module_only_forwarders": fwd_lines,
            "appjs_lines_removed": decl_lines + listener_lines + dep_lines + fwd_lines,
        }

    out = {
        "total_lines": len(lines),
        "modules": {k: {kk: vv for kk, vv in v.items() if kk not in ("deps_block",)}
                    for k, v in modules.items()},
    }
    return out


def main_modules():
    lines = APP.read_text(encoding="utf-8").splitlines()
    out = parse_module_analysis(lines)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if "--modules" in sys.argv[1:]:
        main_modules()
    else:
        main()
