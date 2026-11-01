"""Additional COM2 post-deploy checks. Only read-only checks are run here."""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

MIGRATIONS = ("080", "080a", "081", "082", "083", "084")
TUS_COLLECTION_PATH = "/api/chat/attachments/tus"
DEFAULT_CHAT_UNIT = "padiem-chat-com2.service"


def page_status(opener, url):
    try:
        with opener.open(Request(url, method="GET"), timeout=15) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, OSError, TimeoutError):
        return 0


def chat_process_count(cgroup_procs_path):
    """One number: the app processes systemd currently runs in Chat's cgroup.

    The single-process contract (#6563 edge, #6604 tus, #6610 replay) is only
    real if the cgroup holds exactly one PID. A missing cgroup path answers
    ``None`` so the caller can report an honest SKIP instead of a guess.
    """
    try:
        lines = Path(cgroup_procs_path).read_text(encoding="utf-8").split()
    except (OSError, ValueError):
        return None
    return len(lines)


def tus_capability(opener, base):
    """The public tus creation endpoint answers OPTIONS with its byte ceiling."""
    url = base.rstrip("/") + TUS_COLLECTION_PATH
    try:
        with opener.open(Request(url, method="OPTIONS"), timeout=15) as response:
            status = response.status
            headers = getattr(response, "headers", {})
            maximum = str(headers.get("Tus-Max-Size", "") or "")
    except HTTPError as exc:
        return exc.code, ""
    except (URLError, OSError, TimeoutError, AttributeError):
        return 0, ""
    return status, maximum


def applied_migrations(path):
    try:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            names = [row[0] for row in db.execute(
                "SELECT name FROM padiem_local_migration_ledger"
            )]
    except (OSError, sqlite3.Error, ValueError):
        return None
    found = set()
    for name in names:
        match = re.match(r"^(080a|080|081|082|083|084)(?=_)", str(name))
        if match:
            found.add(match.group(1))
    return [number for number in MIGRATIONS if number in found]


def checks(base, db_path, *, ai_status, ai_code="none", opener=None,
           chat_cgroup_procs=Path("/sys/fs/cgroup/system.slice")
                             / DEFAULT_CHAT_UNIT / "cgroup.procs"):
    opener = opener or build_opener()
    result = [("AI 답변", ai_status, ai_code if ai_status == "FAIL" else "-")]
    # 2026-11-01: /councillor/ is a redirect to the council app; the opener
    # follows it, so a 200 here means the alias still lands on the product.
    for name, route in (("의원 화면", "/apps/council/"), ("의원 화면 별칭(→ /apps/council/)", "/councillor/")):
        status = page_status(opener, base.rstrip("/") + route)
        result.append((name, "PASS" if status == 200 else "FAIL",
                       "-" if status == 200 else "http_" + str(status)))
    # 11-02: two real workers ran on COM2 and the single-process contracts
    # (#6563 edge, #6604 tus, #6610 replay) turned healthy requests into 403s.
    processes = chat_process_count(chat_cgroup_procs)
    if processes is None:
        result.append(("Chat 앱 프로세스 수", "SKIP", "cgroup 경로 없음"))
    elif processes == 1:
        result.append(("Chat 앱 프로세스 수", "PASS", "-"))
    else:
        result.append(("Chat 앱 프로세스 수", "FAIL", f"프로세스 {processes}개"))
    status, maximum = tus_capability(opener, base)
    if status == 204 and maximum.isdigit() and int(maximum) > 0:
        result.append(("tus 이어올리기", "PASS", f"Tus-Max-Size={maximum}"))
    else:
        result.append(("tus 이어올리기", "FAIL", f"http_{status}" if status else "응답 없음"))
    # The mail channels expose no read-only status surface (app.state only),
    # so this row stays a manual check until one exists.
    result.append(("메일 알림 채널", "SKIP", "상태 경로 없음 — 수동 확인"))
    result.extend([
        ("암호 문서 안내", "SKIP", "실사용 파일 점검 미구현"),
        ("HWPX 본문 추출", "SKIP", "실사용 파일 점검 미구현"),
        ("PDF→MD 변환", "SKIP", "변환·정리 점검 미구현"),
        ("견적 XLSX→PDF", "SKIP", "가상 양식 왕복 점검 미구현"),
        ("LibreOffice", "PASS" if shutil.which("soffice") or shutil.which("libreoffice") else "FAIL",
         "-" if shutil.which("soffice") or shutil.which("libreoffice") else "실행 파일 없음"),
    ])
    bookai = page_status(opener, base.rstrip("/") + "/api/bookai/records")
    if bookai == 401:
        result.append(("북AI 기록 API", "PASS", "-"))
    elif bookai == 404:
        result.append(("북AI 기록 API", "SKIP", "해당 없음 — 미배포"))
    else:
        result.append(("북AI 기록 API", "FAIL", "http_" + str(bookai)))
    applied = applied_migrations(db_path)
    result.append(("마이그레이션", "PASS" if applied is not None else "FAIL",
                   ", ".join(applied) if applied else ("적용 없음" if applied is not None else "원장 읽기 실패")))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--chat-db", required=True)
    parser.add_argument("--ai-status", choices=("PASS", "FAIL", "SKIP"), default="SKIP")
    parser.add_argument("--ai-code", default="none")
    parser.add_argument("--chat-unit", default=DEFAULT_CHAT_UNIT)
    args = parser.parse_args()
    code = args.ai_code if re.fullmatch(r"[a-z][a-z0-9_]{0,80}", args.ai_code) else "unknown"
    cgroup = Path("/sys/fs/cgroup/system.slice") / args.chat_unit / "cgroup.procs"
    rows = checks(args.base_url, args.chat_db, ai_status=args.ai_status, ai_code=code,
                  chat_cgroup_procs=cgroup)
    from com2_fixture_probe import run_probes
    fixture_names = {"암호 문서 안내", "HWPX 본문 추출", "PDF→MD 변환", "견적 XLSX→PDF"}
    rows = [row for row in rows if row[0] not in fixture_names]
    rows.extend(run_probes(args.base_url))
    print("| 점검 | 결과 | 이유 |")
    print("| --- | --- | --- |")
    for name, status, reason in rows:
        print(f"| {name} | {status} | {reason} |")
    return 1 if any(status == "FAIL" for _, status, _ in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
