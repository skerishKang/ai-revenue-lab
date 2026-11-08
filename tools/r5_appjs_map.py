#!/usr/bin/env python3
"""R5 0단계-B — app.js 개요 추출기 (#7216).

app.js 를 읽어 최상위 함수/변수와 줄 범위, 함수 간 호출, window 전역 노출,
DOM id, addEventListener 대상을 추출하고 기능 구역별 집계를 JSON 으로 출력한다.
코드 이동 없음. 이 출력만이 모듈 지도 문서의 근거가 된다.

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


def area_of(name):
    for area, rx in AREAS:
        if rx.search(name):
            return area
    return "공통"


def main():
    lines = APP.read_text(encoding="utf-8").splitlines()
    funcs = []
    variables = []
    i = 0
    fn_start = re.compile(r"^  (?:async )?function (\w+)\s*\(")
    var_start = re.compile(r"^  (?:const|let) (\w+)\s*=")
    close_top = re.compile(r"^  }\s*;?\s*$")
    while i < len(lines):
        m = fn_start.match(lines[i])
        if m:
            name = m.group(1)
            start = i + 1
            j = i + 1
            while j < len(lines) and not close_top.match(lines[j]):
                j += 1
            end = j + 1
            funcs.append({"name": name, "start": start, "end": end,
                          "lines": end - start + 1, "area": area_of(name),
                          "body": "\n".join(lines[i:j + 1])})
            i = j + 1
            continue
        v = var_start.match(lines[i])
        if v:
            variables.append({"name": v.group(1), "line": i + 1, "area": area_of(v.group(1))})
        i += 1

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
        a["lines"] += 1
    cross = {}
    for c in calls:
        if c["from_area"] != c["to_area"]:
            key = f"{c['from_area']}->{c['to_area']}"
            cross[key] = cross.get(key, 0) + c["count"]

    out = {
        "total_lines": len(lines),
        "top_level_functions": [{k: f[k] for k in ("name", "start", "end", "lines", "area")} for f in funcs],
        "top_level_variables": variables,
        "calls": [{k: c[k] for k in ("from", "to", "count", "from_area", "to_area")} for c in calls],
        "window_globals": window_globals,
        "dom_ids": dom_ids,
        "listeners": listeners,
        "area_summary": area_summary,
        "cross_area_calls": cross,
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
