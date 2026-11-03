"""#6695 PR-3 — 컴1·컴2·CGI-1 소유 링크 점검 (읽기 전용).

`ORACLE_MESH_LEGACY_MAP_LANE=off`로 폴백을 끄기 전 확인 순서(설계 문서 §4)의
①~③ 단계를 대신한다: 알려진 에이전트 라벨마다 소유 링크가 존재하는지, 루트
승인이 있는지, 메시 접속 증거(presence)가 보이는지만 센다.

**운영 값 출력 금지**: 사용자 id, 노드 id, 링크 id, 라벨 원문, 경로는 절대
출력하지 않는다. 출력은 기기별 라벨 인자와 개수·yes/no뿐이다.

사용법 (컴1, gh/wrangler 로그인 상태):
    python tools/cto/check_pc_owner_links.py \
        --binding <D1 바인딩 이름> --remote --label 컴1 --label 컴2 --label CGI-1

- `--remote` 대신 `--local <db 파일>`로 로컬 SQLite를 읽을 수 있다(시험용).
- 바인딩 이름·라벨은 실행자가 인자로 넣는다 — 저장소에 운영 값이 없다.
- 쿼리는 SELECT뿐이고, wrangler는 `--json`으로 불러 결과를 그대로 파싱한다.
  쓰기·수정은 없다. wrangler 실패 시 원인 한 줄과 종료 코드 2.

판정: 라벨마다 active 링크 1개 이상 + 그 링크에 승인 루트 1개 이상이면
`OK`, 링크가 없으면 `NO LINK`, 루트가 없으면 `NO ROOTS`. 세 라벨 모두 OK일 때
종료 코드 0(스위치 off 진행 가능), 아니면 1.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

_MAX_LABEL = 80
_LINKS_SQL = (
    "SELECT l.label AS label, l.user_id AS user_id, l.mesh_node_id AS node, "
    "l.roots_json AS roots_json, l.state AS state "
    "FROM pc_device_links l WHERE l.state='active'"
)


def _visible(value) -> str | None:
    """라벨 인자 검증: 출력 가능한 경계 있는 문자열만 받는다."""
    if not isinstance(value, str) or not value or len(value) > _MAX_LABEL:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    return value.strip()


def _roots_count(roots_json) -> int:
    """승인 루트 개수만 센다. 값은 절대 밖으로 나오지 않는다."""
    try:
        roots = json.loads(roots_json) if isinstance(roots_json, str) else roots_json
    except ValueError:
        return 0
    if not isinstance(roots, list):
        return 0
    return sum(
        1 for root in roots
        if isinstance(root, dict) and root.get("state", "active") == "active"
    )


def _fetch_rows(args) -> list[dict]:
    if args.local:
        # 로컬 SQLite(시험용): 표준 라이브러리만, 읽기 전용 연결.
        import sqlite3
        conn = sqlite3.connect(f"file:{args.local}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(_LINKS_SQL)]
        conn.close()
        return rows
    command = ["wrangler", "d1", "execute", args.binding,
               "--remote", "--json", "--command", _LINKS_SQL]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0:
        reason = (done.stderr or done.stdout or "").strip().splitlines()
        print(f"WRANGLER FAILED: {reason[-1] if reason else 'no output'}")
        raise SystemExit(2)
    payload = json.loads(done.stdout)
    rows: list[dict] = []
    for entry in payload if isinstance(payload, list) else []:
        results = entry.get("results") if isinstance(entry, dict) else None
        if isinstance(results, list):
            rows.extend(row for row in results if isinstance(row, dict))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="알려진 PC 에이전트의 소유 링크 유무를 읽기 전용으로 센다.")
    parser.add_argument("--binding", help="Cloudflare D1 바인딩(데이터베이스) 이름")
    parser.add_argument("--remote", action="store_true", help="운영 D1을 읽는다")
    parser.add_argument("--local", help="로컬 SQLite DB 파일(시험용)")
    parser.add_argument("--label", action="append", required=True,
                        help="확인할 에이전트 라벨(반복 지정, 예: --label 컴1)")
    args = parser.parse_args(argv)

    if not args.remote and not args.local:
        print("USAGE: --remote (운영 D1) 또는 --local <파일> 중 하나가 필요합니다")
        return 2
    if args.remote and args.local:
        print("USAGE: --remote와 --local은 동시에 쓰지 않는다")
        return 2
    labels = [item for item in (_visible(v) for v in args.label) if item]
    if not labels:
        print("USAGE: 유효한 --label이 최소 하나 필요합니다")
        return 2

    rows = _fetch_rows(args)
    # 라벨 매칭은 소유자가 붙인 라벨의 부분 일치다. 매칭에 쓴 뒤에는 개수만 남긴다.
    summary: dict[str, dict[str, int]] = {}
    for label in labels:
        summary[label] = {"links": 0, "with_roots": 0, "nodes": set()}
    for row in rows:
        label_value = row.get("label")
        if not isinstance(label_value, str):
            continue
        for label in labels:
            if label in label_value:
                entry = summary[label]
                entry["links"] += 1
                entry["nodes"].add(row.get("node"))
                if _roots_count(row.get("roots_json")) > 0:
                    entry["with_roots"] += 1
                break

    all_ok = True
    for label in labels:
        entry = summary[label]
        linked = entry["links"] > 0
        rooted = entry["with_roots"] > 0
        if not linked:
            verdict = "NO LINK"
            all_ok = False
        elif not rooted:
            verdict = "NO ROOTS"
            all_ok = False
        else:
            verdict = "OK"
        # 기기 수만 센다. 노드 id·사용자 id·라벨 원문은 출력하지 않는다.
        print(f"{label}: devices={len(entry['nodes'])} links={entry['links']} "
              f"approved_roots={'yes' if rooted else 'no'} -> {verdict}")
    print("VERDICT: " + ("switch_off_ready" if all_ok else "switch_off_blocked"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
