"""Read-only COM2 smoke checks and honest reporting for incomplete probes."""
import importlib.util
import sqlite3
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "post_deploy_smoke.py"
spec = importlib.util.spec_from_file_location("com2_post_deploy_smoke", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Response:
    def __init__(self, status, headers=None):
        self.status = status
        self.headers = headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass


class FakeOpener:
    def __init__(self):
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        if request.method == "OPTIONS" and request.full_url.endswith("/api/chat/attachments/tus"):
            return Response(204, headers={"Tus-Max-Size": "104857600"})
        return Response(200 if request.full_url.endswith("/apps/council/") else 503)


def test_migration_ledger_is_read_only_and_preserves_080a(tmp_path):
    path = tmp_path / "chat.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE padiem_local_migration_ledger (name TEXT)")
        db.executemany("INSERT INTO padiem_local_migration_ledger VALUES (?)", [
            ("080_owner.sql",), ("080a_backfill.sql",), ("083_test.sql",),
        ])
    assert module.applied_migrations(path) == ["080", "080a", "083"]
    assert module.applied_migrations(tmp_path / "missing.sqlite3") is None
    assert not (tmp_path / "missing.sqlite3").exists()


def test_verdicts_report_unimplemented_checks_as_skipped(tmp_path, monkeypatch):
    opener = FakeOpener()
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    rows = module.checks("https://example.test", tmp_path / "missing.sqlite3",
                         ai_status="FAIL", ai_code="upstream_unavailable",
                         opener=opener,
                         chat_cgroup_procs=tmp_path / "missing-cgroup" / "cgroup.procs")
    results = {name: (status, reason) for name, status, reason in rows}
    # The alias row was renamed on 2026-11-01: /councillor/ is a deliberate
    # alias check now, and the opener answers 503 for it in this fixture.
    assert results["의원 화면 별칭(→ /apps/council/)"] == ("FAIL", "http_503")
    assert results["AI 답변"] == ("FAIL", "upstream_unavailable")
    assert results["의원 화면"][0] == "PASS"
    assert results["마이그레이션"][0] == "FAIL"
    assert results["견적 XLSX→PDF"][0] == "SKIP"
    assert all(request.method in {"GET", "OPTIONS"} for request in opener.requests)


def test_new_single_process_and_tus_rows(tmp_path, monkeypatch):
    opener = FakeOpener()
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    cgroup = tmp_path / "cgroup.procs"
    cgroup.write_text("101\n202\n")
    rows = module.checks("https://example.test", tmp_path / "missing.sqlite3",
                         ai_status="PASS", opener=opener, chat_cgroup_procs=cgroup)
    results = {name: (status, reason) for name, status, reason in rows}
    # (a) the single-process contract is verified against the cgroup itself.
    assert results["Chat 앱 프로세스 수"] == ("FAIL", "프로세스 2개")
    cgroup.write_text("101\n")
    rows = module.checks("https://example.test", tmp_path / "missing.sqlite3",
                         ai_status="PASS", opener=opener, chat_cgroup_procs=cgroup)
    results = {name: (status, reason) for name, status, reason in rows}
    assert results["Chat 앱 프로세스 수"] == ("PASS", "-")
    # (b) the public tus capability answers OPTIONS 204 with its byte ceiling.
    assert results["tus 이어올리기"] == ("PASS", "Tus-Max-Size=104857600")
    # (c) the mail channels have no read-only status surface yet: honest SKIP.
    assert results["메일 알림 채널"] == ("SKIP", "상태 경로 없음 — 수동 확인")
    missing = tmp_path / "nope" / "cgroup.procs"
    rows = module.checks("https://example.test", tmp_path / "missing.sqlite3",
                         ai_status="PASS", opener=opener, chat_cgroup_procs=missing)
    results = {name: (status, reason) for name, status, reason in rows}
    assert results["Chat 앱 프로세스 수"] == ("SKIP", "cgroup 경로 없음")


def test_tus_capability_reports_refusals_and_missing_ceiling():
    class OptionsOpener:
        def __init__(self, status, headers):
            self.status, self.headers = status, headers
        def open(self, request, timeout):
            assert request.method == "OPTIONS"
            assert request.full_url.endswith("/api/chat/attachments/tus")
            return Response(self.status, headers=self.headers)
    assert module.tus_capability(OptionsOpener(405, {}), "https://example.test") == (405, "")
    assert module.tus_capability(
        OptionsOpener(204, {}), "https://example.test") == (204, "")
    assert module.tus_capability(OptionsOpener(0, {}), "https://example.test") == (0, "")


def test_bookai_unsigned_status_and_absent_route(tmp_path, monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    class BookOpener:
        def __init__(self, status):
            self.status = status
        def open(self, request, timeout):
            if request.full_url.endswith("/api/bookai/records"):
                return Response(self.status)
            return Response(200)
    for status, expected in [(401, "PASS"), (404, "SKIP"), (200, "FAIL"), (503, "FAIL")]:
        rows = module.checks("https://example.test", tmp_path / "missing.sqlite3",
                             ai_status="PASS", opener=BookOpener(status))
        assert next(row[1] for row in rows if row[0] == "북AI 기록 API") == expected
