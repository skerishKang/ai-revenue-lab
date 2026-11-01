"""Read-only COM2 smoke checks and honest reporting for incomplete probes."""
import importlib.util
import sqlite3
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "post_deploy_smoke.py"
spec = importlib.util.spec_from_file_location("com2_post_deploy_smoke", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Response:
    def __init__(self, status):
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass


class FakeOpener:
    def __init__(self):
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
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
                         ai_status="FAIL", ai_code="upstream_unavailable", opener=opener)
    results = {name: (status, reason) for name, status, reason in rows}
    assert results["AI 답변"] == ("FAIL", "upstream_unavailable")
    assert results["의원 화면"][0] == "PASS"
    assert results["의원 활동 화면"] == ("FAIL", "http_503")
    assert results["마이그레이션"][0] == "FAIL"
    assert results["견적 XLSX→PDF"][0] == "SKIP"
    assert all(request.method == "GET" for request in opener.requests)



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
