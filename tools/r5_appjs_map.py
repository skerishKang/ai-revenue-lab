#!/usr/bin/env python3
"""R5 0단계-B — app.js 개요 추출기 (#7216).

app.js 를 읽어 최상위 함수/변수와 줄 범위, 함수 간 호출, window 전역 노출,
DOM id, addEventListener 대상을 추출하고 기능 구역별 집계를 JSON 으로 출력한다.
코드 이동 없음. 이 출력만이 모듈 지도 문서의 근거가 된다.

2026-11-09 보완: 구역별 함수·변수 줄 합과 전체 줄 수의 차이(약 1,700줄)를
설명하기 위해 함수 밖 최상위 코드 블록(이벤트 연결·초기화·즉시 실행)과
주석/빈 줄을 따로 세어 line_accounting 으로 출력한다.

사용: python tools/r5_appjs_map.py [app.js 경로]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "apps/padiem-chat/static/app.js"

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


def find_close_top(lines, i):
    j = i + 1
    while j < len(lines) and lines[j] != "  }" and not re.match(r"^  }\s*;?\s*$", lines[j]):
        j += 1
    return j


def variable_end(lines, i):
    """Multi-line initializers: consume until bracket depth returns to zero."""
    depth = 0
    in_block_comment = False
    for j in range(i, len(lines)):
        line = lines[j]
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
            continue
        if "/*" in line and "*/" not in line.split("/*", 1)[1]:
            in_block_comment = True
        code = re.sub(r"//.*$", "", line)
        code = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`\\]|\\.)*`", "", code)
        depth += code.count("(") - code.count(")") + code.count("{") - code.count("}") + code.count("[") - code.count("]")
        if j > i and depth <= 0:
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
                 re.findall(r"([A-Za-z_$][\w$]*)\.addEventListener\(\s*[\"'](\w+)[\"']", text)]

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


if __name__ == "__main__":
    main()
