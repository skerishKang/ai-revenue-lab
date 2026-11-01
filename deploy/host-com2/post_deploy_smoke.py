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


def page_status(opener, url):
    try:
        with opener.open(Request(url, method="GET"), timeout=15) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, OSError, TimeoutError):
        return 0


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


def checks(base, db_path, *, ai_status, ai_code="none", opener=None):
    opener = opener or build_opener()
    result = [("AI 답변", ai_status, ai_code if ai_status == "FAIL" else "-")]
    for name, route in (("의원 화면", "/apps/council/"), ("의원 활동 화면", "/councillor/")):
        status = page_status(opener, base.rstrip("/") + route)
        result.append((name, "PASS" if status == 200 else "FAIL",
                       "-" if status == 200 else "http_" + str(status)))
    result.extend([
        ("암호 문서 안내", "SKIP", "실사용 파일 점검 미구현"),
        ("HWPX 본문 추출", "SKIP", "실사용 파일 점검 미구현"),
        ("PDF→MD 변환", "SKIP", "변환·정리 점검 미구현"),
        ("견적 XLSX→PDF", "SKIP", "가상 양식 왕복 점검 미구현"),
        ("LibreOffice", "PASS" if shutil.which("soffice") or shutil.which("libreoffice") else "FAIL",
         "-" if shutil.which("soffice") or shutil.which("libreoffice") else "실행 파일 없음"),
        ("북AI 기록 API", "SKIP", "API 경로 미확인"),
    ])
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
    args = parser.parse_args()
    code = args.ai_code if re.fullmatch(r"[a-z][a-z0-9_]{0,80}", args.ai_code) else "unknown"
    rows = checks(args.base_url, args.chat_db, ai_status=args.ai_status, ai_code=code)
    print("| 점검 | 결과 | 이유 |")
    print("| --- | --- | --- |")
    for name, status, reason in rows:
        print(f"| {name} | {status} | {reason} |")
    return 1 if any(status == "FAIL" for _, status, _ in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
