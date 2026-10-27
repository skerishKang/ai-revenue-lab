"""#5927 follow-up — the PADIEM app ↔ platform contract cannot drift silently.

The contract itself lives in `.github/scripts/padiem_apps_integration_contract.py`.
These tests do two things: prove it holds against the real source today, and prove
each guard actually fires when the source it pins changes. A contract that cannot
fail is not a boundary, so every check here is written as a refusal test.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / ".github/scripts/padiem_apps_integration_contract.py"

spec = importlib.util.spec_from_file_location("padiem_apps_integration_contract", CONTRACT)
assert spec and spec.loader
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def swap(monkeypatch, name: str, content: str, tmp_path: Path) -> None:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(contract, name, path)


def test_the_platform_offers_exactly_what_the_contract_claims() -> None:
    assert contract.findings() == []


def test_the_route_set_is_closed_and_methods_are_not_widened() -> None:
    paths = {path for _name, _methods, path in contract.PLATFORM_ROUTES}
    assert paths == {
        "/api/auth/status",
        "/api/auth/password/login",
        "/api/chat",
        "/api/projects",
        "/api/projects/{project_id}/files",
        "/api/projects/{project_id}/files/{file_id}",
        "/api/projects/{project_id}/files/{file_id}/original",
    }
    # A contract route an app may not call is one that is not registered at all.
    assert "PLATFORM_ROUTE_FILE_DETAIL_MISSING" not in contract.findings()
    assert "PLATFORM_ROUTE_LOGIN_MISSING" not in contract.findings()
    # The app may sign a visitor in; it may not register one, reset a password or
    # end someone else's session. Those stay Chat's, not an app's.
    for beyond in ("/api/auth/password/register", "/api/auth/password/reset/request",
                   "/api/auth/logout", "/auth/google/callback"):
        assert beyond not in paths, beyond


def test_the_ai_lane_is_the_existing_chat_lane_not_a_second_router() -> None:
    generate = next(entry for entry in contract.PLATFORM_ROUTES if entry[0] == "generate")
    assert generate[1:] == (("POST",), "/api/chat")
    # The AI authority is asserted by the proof + binding checks below rather than
    # by a second implementation here.
    assert "B14_SERVICE_PROOF_AUTHORITY_DRIFT" not in contract.findings()
    assert "B14_LANE_BINDING_DRIFT" not in contract.findings()


def test_work_scopes_are_routing_labels_and_an_unknown_one_is_refused(tmp_path, monkeypatch) -> None:
    real = contract._read(contract.REQUEST_CONTRACT)
    assert "grants no identity, tier" in real or "not an authentication input" in real

    widened = real.replace('_UTIL_SCOPES = frozenset({"speech", "sns", "meeting"})',
                           '_UTIL_SCOPES = frozenset({"speech", "sns", "meeting", "admin"})')
    assert widened != real
    swap(monkeypatch, "REQUEST_CONTRACT", widened, tmp_path)
    assert "WORK_SCOPE_AUTHORITY_DRIFT" in contract.findings()

    unrefused = real.replace(
        'raise BrowserRequestError("유틸 업무 식별자가 올바르지 않습니다.")',
        "pass")
    swap(monkeypatch, "REQUEST_CONTRACT", unrefused, tmp_path)
    assert "WORK_SCOPE_NOT_REFUSED" in contract.findings()


def test_the_calendar_branch_guard_cannot_be_softened(tmp_path, monkeypatch) -> None:
    real = contract._read(contract.CHAT_ROUTES)
    swap(monkeypatch, "CHAT_ROUTES", real.replace("util_scope is None", "True"), tmp_path)
    assert "CALENDAR_BRANCH_NOT_GUARDED" in contract.findings()


def test_the_origin_expectation_stays_server_owned(tmp_path, monkeypatch) -> None:
    """A bridge that forwarded the caller's Origin would empty this guard."""

    real = contract._read(contract.ORIGIN_GUARD)
    swap(monkeypatch, "ORIGIN_GUARD",
         real.replace("Only ``Settings.public_base_url`` is consulted",
                      "the request Host is consulted"), tmp_path)
    assert "ORIGIN_AUTHORITY_DRIFT" in contract.findings()

    unclassified = real.replace("**B — read-only (GET/HEAD):** out of scope", "**B:**")
    swap(monkeypatch, "ORIGIN_GUARD", unclassified, tmp_path)
    assert "ORIGIN_GUARD_CLASS_B_UNDOCUMENTED" in contract.findings()


def test_the_session_read_still_does_not_carry_a_user_id(tmp_path, monkeypatch) -> None:
    """The reason a separate origin needs same-host routing, not a new endpoint."""

    real = contract._read(contract.HISTORY)
    leaking = real.replace('return {"email": self.email, "name": self.display_name, "picture": self.picture_url}',
                           'return {"uid": self.user_id, "email": self.email,'
                           ' "name": self.display_name, "picture": self.picture_url}')
    assert leaking != real
    swap(monkeypatch, "HISTORY", leaking, tmp_path)
    assert "AUTH_STATUS_PROJECTION_CHANGED" in contract.findings()


def test_the_storage_ceilings_and_media_are_the_existing_ones(tmp_path, monkeypatch) -> None:
    swap(monkeypatch, "PROJECT_FILE_ROUTES",
         contract._read(contract.PROJECT_FILE_ROUTES).replace("MAX_PROJECT_FILE_BODY_BYTES = 160_000",
                                                              "MAX_PROJECT_FILE_BODY_BYTES = 999"),
         tmp_path)
    assert "STORED_BODY_LIMIT_DRIFT" in contract.findings()

    swap(monkeypatch, "PROJECT_FILES",
         contract._read(contract.PROJECT_FILES).replace("PROJECT_FILE_MAX_CONTENT_CHARS = 40_000",
                                                        "PROJECT_FILE_MAX_CONTENT_CHARS = 10"),
         tmp_path)
    assert "STORED_CHARS_LIMIT_DRIFT" in contract.findings()

    narrowed = contract._read(contract.DOCUMENT_NORMALIZATION).replace('"application/json": frozenset({".json"}),', "")
    swap(monkeypatch, "DOCUMENT_NORMALIZATION", narrowed, tmp_path)
    assert "STORED_TEXT_MEDIA_JSON_UNAVAILABLE" in contract.findings()


def test_a_new_canonical_product_id_cannot_be_assumed(tmp_path, monkeypatch) -> None:
    real = contract._read(contract.IDENTITY_AUTHORITY)
    widened = real.replace('frozenset({"b62", "b54-padiem-claw", "lovetree-4-0"})',
                           'frozenset({"b62", "b54-padiem-claw", "lovetree-4-0", "b72"})')
    assert widened != real
    swap(monkeypatch, "IDENTITY_AUTHORITY", widened, tmp_path)
    assert "IDENTITY_PRODUCT_ALLOWLIST_DRIFT" in contract.findings()


def test_a_missing_platform_route_is_reported_by_name(tmp_path, monkeypatch) -> None:
    factory = contract._read(contract.APP_FACTORY)
    swap(monkeypatch, "APP_FACTORY",
         factory.replace('Route("/api/projects/{project_id}/files/{file_id}",', 'Route("/removed",'),
         tmp_path)
    assert contract.findings() == ["PLATFORM_ROUTE_FILE_DETAIL_MISSING"]


def test_the_cli_reports_exact_then_drift(tmp_path, monkeypatch) -> None:
    assert contract.main(["check"]) == 0
    assert contract.main(["describe"]) == 0
    swap(monkeypatch, "APP_FACTORY", "", tmp_path)
    assert contract.main(["check"]) == 1


def test_no_app_side_duplicate_of_the_platform_authorities() -> None:
    """An app must not grow its own copy of the model router, the session cookie
    or the file store while this contract exists."""

    auth_source = contract._read(ROOT / "apps/padiem-chat/app/auth.py")
    assert "padiem_session" in auth_source
    assert "SESSION_COOKIE" in auth_source
    assert "_UTIL_SCOPES" in contract._read(contract.REQUEST_CONTRACT)

    # The Chat Worker's own session cookie name stays single-sourced.
    cookie_declarations = [
        p for p in (ROOT / "apps/padiem-chat/app").glob("*.py")
        if "SESSION_COOKIE = " in p.read_text(encoding="utf-8")
    ]
    assert [p.name for p in cookie_declarations] == ["auth.py"]


def test_the_checker_runs_as_a_plain_script() -> None:
    done = subprocess.run([sys.executable, str(CONTRACT), "check"],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PADIEM_APPS_CONTRACT=EXACT" in done.stdout
    assert "PRODUCTION_MUTATION=0" in done.stdout
    payload = json.loads(subprocess.run([sys.executable, str(CONTRACT), "describe"],
                                        capture_output=True, text=True, check=False).stdout)
    assert payload["work_scopes"] == ["meeting", "sns", "speech"]
    assert payload["max_stored_body_bytes"] == 160_000
