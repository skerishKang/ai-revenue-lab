"""#2812: /api/claw/manual-intake/quote-compare wiring evidence.

The Claw Ops audit found the deterministic supplier comparison engine had zero
HTTP wiring. These tests pin the opposite: the route must call the real
``SupplierComparisonEngine``, must never reach P01/Engine/B14/quota/history, and
must hand its document to the existing bounded artifact + download path.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

from kagent.ops_comparison import SupplierComparisonEngine

COMPARE_ROUTE = "/api/claw/manual-intake/quote-compare"
ARTIFACT_ROUTE_TEMPLATE = "/api/claw/manual-intake/artifact/{document_id}"
SIGNED_IN_USER_ID = "usr_" + "7" * 32
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SUPPLIER_A = {
    "supplier_id": "supplier_a",
    "supplier_label": "A업체",
    "item_label": "산업용 랙",
    "quantity": "10",
    "unit_price_minor": 120000,
    "total_minor": 1200000,
    "promised_delivery_date": "2026-10-05",
    "payment_terms": {"label": "월말매입 30일", "due_days": 30, "prepaid": False},
    "evidence_ref": "A업체 견적서 2026-09-18",
}
SUPPLIER_B = {
    "supplier_id": "supplier_b",
    "supplier_label": "B업체",
    "item_label": "산업용 랙",
    "total_minor": 1050000,
    "promised_delivery_date": "2026-10-20",
    "payment_terms": {"label": "선입금", "due_days": 0, "prepaid": True},
}
SUPPLIER_UNKNOWN = {
    "supplier_id": "supplier_c",
    "supplier_label": "C업체",
    "item_label": "산업용 랙",
    "total_minor": 1150000,
}


def _payload(*suppliers: dict[str, object], **top: object) -> dict[str, object]:
    body: dict[str, object] = {"suppliers": list(suppliers)}
    body.update(top)
    return body


def _settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "live_enabled": "false",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "quote-gate-client.apps.googleusercontent.com",
        "google_client_secret": "quote-gate-google-secret",
        "session_secret": "quote-compare-session-secret-not-a-real-credential-0",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


@pytest.fixture
def client() -> TestClient:
    app = create_app(settings=Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"))
    return TestClient(app)


class _RoundTripDocumentStore:
    """In-memory stand-in with the real put/get signatures and tenant check."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[object, bytes]] = {}
        self.put_calls: list[dict[str, object]] = []

    async def put_generated_docx(self, *, tenant_id: str, filename: str, body: bytes):
        self.put_calls.append({"tenant_id": tenant_id, "filename": filename, "body": body})
        document_id = "doc_" + hashlib.sha256(filename.encode("utf-8")).hexdigest()[:32]
        metadata = MagicMock()
        metadata.document_id = document_id
        metadata.tenant_id = tenant_id
        metadata.filename = filename
        metadata.media_type = DOCX_MEDIA_TYPE
        metadata.byte_length = len(body)
        metadata.public_projection.return_value = {
            "document_id": document_id,
            "filename": filename,
            "media_type": DOCX_MEDIA_TYPE,
            "byte_length": len(body),
        }
        self.rows[document_id] = (metadata, body)
        return metadata

    async def get_for_tenant(self, *, tenant_id: str, document_id: str):
        record = self.rows.get(document_id)
        if record is None or record[0].tenant_id != tenant_id:
            return None
        return record


def _identity_shadow_store() -> MagicMock:
    now = datetime.now(timezone.utc)
    store = MagicMock()
    store.load_projection = AsyncMock(
        return_value=IdentityShadowRecord(
            product_user_id=SIGNED_IN_USER_ID,
            canonical_subject_id="subject_test",
            auth_session_id="session_test123",
            session_revision=1,
            session_state="active",
            session_expires_at=now + timedelta(hours=1),
            observed_at=now,
        )
    )
    return store


def _authority() -> MagicMock:
    now = datetime.now(timezone.utc)
    snapshot = AuthSessionSnapshot(
        session_id="session_test123",
        product_id=PADIEM_CHAT_PRODUCT_ID,
        subject=CanonicalSubjectRef(SubjectType.USER, "subject_test"),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id="tenant_test",
    )
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(return_value=snapshot)
    return authority


def _signed_in_client(store: _RoundTripDocumentStore | None = None) -> TestClient:
    app = create_app(
        settings=_settings(),
        history_store=MagicMock(),
        d1_binding=MagicMock(),
        r2_binding=MagicMock(),
    )
    app.state.identity_shadow_store = _identity_shadow_store()
    app.state.control_plane_identity_authority = _authority()
    if store is not None:
        app.state.workspace_document_store = store
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    return client


class _RecordingUsageGate:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    async def authorize(self, *, raw_ip, user_id):
        self.calls.append((raw_ip, user_id))
        raise AssertionError("the deterministic quote comparison must not consume quota")


def test_route_returns_the_engines_deterministic_recommendation(client: TestClient) -> None:
    resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B, mode="lowest_price"))
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store, max-age=0"
    comparison = resp.json()["comparison"]
    assert comparison["recommended_supplier_id"] == "supplier_b"
    assert comparison["mode"] == "lowest_price"
    assert comparison["supplier_count"] == 2
    assert [item["supplier_id"] for item in comparison["suppliers"]] == ["supplier_b", "supplier_a"]
    assert comparison["suppliers"][0]["price_rank"] == 1
    assert comparison["reason_codes"][0] == "mode:lowest_price"


def test_route_is_reproducible_for_the_same_capture(client: TestClient) -> None:
    body = _payload(SUPPLIER_A, SUPPLIER_B, SUPPLIER_UNKNOWN)
    first = client.post(COMPARE_ROUTE, json=body).json()
    second = client.post(COMPARE_ROUTE, json=body).json()
    assert first == second


def test_route_calls_the_real_ops_comparison_engine(client: TestClient) -> None:
    original = SupplierComparisonEngine.evaluate
    seen: list[tuple[int, str]] = []

    def spy(self, quotes, **kwargs):
        seen.append((len(quotes), str(kwargs.get("mode"))))
        return original(self, quotes, **kwargs)

    with patch.object(SupplierComparisonEngine, "evaluate", autospec=True, side_effect=spy):
        resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B, SUPPLIER_UNKNOWN))
    assert resp.status_code == 200
    assert seen == [(3, "ComparisonMode.BALANCED")]
    comparison = resp.json()["comparison"]
    # score_basis_points only exist on the engine's own analysis object.
    assert all(isinstance(item["score_basis_points"], int) for item in comparison["suppliers"])


def test_route_negotiation_target_comes_from_the_engine_not_a_model(client: TestClient) -> None:
    original = SupplierComparisonEngine.negotiation_target_from_competing_quote
    with patch.object(
        SupplierComparisonEngine, "negotiation_target_from_competing_quote", autospec=True
    ) as stub:
        stub.side_effect = lambda self, **kwargs: original(self, **kwargs)
        resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B))
    assert stub.call_count == 1
    negotiation = resp.json()["comparison"]["negotiation"]
    assert negotiation["target_total"] == {"amount_minor": 1050000, "currency": "KRW"}
    assert negotiation["basis"] == "captured_competing_quote:quote_supplier_b:v1"


def test_missing_captures_stay_unknown_on_the_http_surface(client: TestClient) -> None:
    resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_UNKNOWN))
    assert resp.status_code == 200
    unknown = next(
        item for item in resp.json()["comparison"]["suppliers"] if item["supplier_id"] == "supplier_c"
    )
    assert unknown["promised_delivery_date"] is None
    assert unknown["payment_terms_label"] == ""
    assert unknown["due_days"] is None
    assert unknown["prepaid"] is None
    assert unknown["unknown_fields"] == ["promised_delivery_date", "payment_terms"]


def test_evidence_reference_survives_the_http_projection(client: TestClient) -> None:
    resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B))
    captured = next(
        item for item in resp.json()["comparison"]["suppliers"] if item["supplier_id"] == "supplier_a"
    )
    assert captured["evidence_ref"] == "A업체 견적서 2026-09-18"


def test_single_supplier_is_safe_and_declines_to_invent_a_target(client: TestClient) -> None:
    resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A))
    assert resp.status_code == 200
    comparison = resp.json()["comparison"]
    assert comparison["recommended_supplier_id"] == "supplier_a"
    assert comparison["negotiation"] is None
    assert comparison["negotiation_unavailable_reason"] == "single_supplier_no_competing_quote"


def test_projection_declares_draft_only_and_zero_side_effects(client: TestClient) -> None:
    comparison = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B)).json()["comparison"]
    assert comparison["draft_only"] is True
    assert comparison["external_send_supported"] is False
    assert comparison["external_sends"] == 0
    assert comparison["model_calls"] == 0
    assert comparison["advisory_only"] is True
    assert comparison["negotiation"]["status"] == "draft_only"
    assert comparison["negotiation"]["send_performed"] is False


def test_route_never_dispatches_p01_quota_or_history(client: TestClient) -> None:
    app = create_app(
        settings=_settings(),
        history_store=MagicMock(),
        d1_binding=MagicMock(),
        r2_binding=MagicMock(),
    )
    app.state.usage_gate = _RecordingUsageGate()
    app.state.usage_gate_enforced = True
    adapter = MagicMock()
    adapter.execute = AsyncMock(side_effect=AssertionError("P01 must not be reached"))
    app.state.claw_p01_adapter = adapter
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B))
    assert resp.status_code == 200
    assert app.state.usage_gate.calls == []
    adapter.execute.assert_not_called()
    app.state.history_store.record_claw_run.assert_not_called()


def test_artifact_is_stored_and_downloaded_through_the_existing_path() -> None:
    store = _RoundTripDocumentStore()
    client = _signed_in_client(store)
    resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B, SUPPLIER_UNKNOWN, artifact="docx"))
    assert resp.status_code == 200
    descriptor = resp.json()["artifact"]
    assert descriptor["document_id"].startswith("doc_")
    assert descriptor["media_type"] == DOCX_MEDIA_TYPE
    assert descriptor["byte_length"] > 0
    assert len(store.put_calls) == 1
    assert store.put_calls[0]["tenant_id"] == "tenant_test"

    body = store.put_calls[0]["body"]
    with zipfile.ZipFile(io.BytesIO(body)) as package:
        document_xml = package.read("word/document.xml").decode("utf-8")
    for marker in ("공급업체 견적 비교", "산업용 랙", "미확인", "DRAFT ONLY", "1,200,000 KRW"):
        assert marker in document_xml

    download = client.get(ARTIFACT_ROUTE_TEMPLATE.format(document_id=descriptor["document_id"]))
    assert download.status_code == 200
    assert download.headers["content-type"] == DOCX_MEDIA_TYPE
    assert download.content == body
    assert "attachment" in download.headers["content-disposition"]


def test_artifact_requires_canonical_tenant_and_store(client: TestClient) -> None:
    resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B, artifact="docx"))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "workspace_scope_unavailable"

    signed_in = _signed_in_client(None)
    if hasattr(signed_in.app.state, "workspace_document_store"):
        del signed_in.app.state.workspace_document_store
    resp = signed_in.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B, artifact="docx"))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "workspace_storage_unavailable"


def test_comparison_without_artifact_needs_no_storage_authority(client: TestClient) -> None:
    assert client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B)).status_code == 200


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"suppliers": []}, "suppliers_required"),
        ({"suppliers": [{"supplier_id": "s1"}]}, "supplier_price_missing"),
        ({"suppliers": [{"supplier_id": "s1", "total_minor": 1.5}]}, "invalid_price"),
        (
            {"suppliers": [{"supplier_id": "s1", "total_minor": 100, "promised_delivery_date": "2주"}]},
            "invalid_delivery_date",
        ),
        ({"suppliers": [SUPPLIER_A, SUPPLIER_B], "mode": "cheapest_by_llm"}, "invalid_comparison_mode"),
        ({"suppliers": [SUPPLIER_A, SUPPLIER_B], "weights": {"price": 60}}, "invalid_comparison_weights"),
        ({"suppliers": [{"supplier_id": "s1", "total_minor": 100, "quantity": "한무지개"}]}, "invalid_quantity"),
        ({"suppliers": "A업체 100만원"}, "suppliers_required"),
        ({}, "suppliers_required"),
    ],
)
def test_malformed_input_fails_closed_with_a_bounded_code(
    client: TestClient, body: dict[str, object], code: str
) -> None:
    resp = client.post(COMPARE_ROUTE, json=body)
    assert resp.status_code == 400
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["message"], str) and payload["error"]["message"]


@pytest.mark.parametrize("body", [{"suppliers": [SUPPLIER_A, SUPPLIER_B], "mode": "llm_choice"}, {}])
def test_fail_closed_input_never_reaches_the_engine(client: TestClient, body: dict[str, object]) -> None:
    with patch.object(
        SupplierComparisonEngine,
        "evaluate",
        side_effect=AssertionError("engine must not run for invalid input"),
    ):
        resp = client.post(COMPARE_ROUTE, json=body)
    assert resp.status_code == 400


def test_transport_level_input_failures_are_bounded(client: TestClient) -> None:
    resp = client.post(COMPARE_ROUTE, content="not json", headers={"content-type": "application/json"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_json"

    resp = client.post(COMPARE_ROUTE, content=b"", headers={"content-type": "application/json"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "empty_request_body"

    resp = client.post(COMPARE_ROUTE, content="plain", headers={"content-type": "text/plain"})
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_media_type"

    oversize = _payload(*([{
        "supplier_id": f"s{i}",
        "total_minor": 100 + i,
        "supplier_label": "업체" * 40,
    } for i in range(500)]))
    resp = client.post(COMPARE_ROUTE, content=json.dumps(oversize).encode("utf-8"), headers={"content-type": "application/json"})
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "request_too_large"


def test_unsupported_artifact_format_fails_closed(client: TestClient) -> None:
    for value in ("hwp", "hwpx", "md", True, 1):
        resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, artifact=value))
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_artifact_format"


def test_existing_manual_intake_preview_is_unchanged(client: TestClient) -> None:
    resp = client.post(
        "/api/claw/manual-intake/preview",
        json={
            "content": "가상 테스트: A업체가 9월 말까지 샘플 20개 견적서를 요청함.",
            "channel": "kakao",
            "action": "quote",
            "sender_hint": "A업체",
        },
    )
    assert resp.status_code == 200
    preview = resp.json()["preview"]
    assert preview["action"] == "quote_draft"
    assert preview["direct_kakao_send"] is False
    assert "artifact" not in preview


def test_response_never_echoes_unbounded_or_private_fields(client: TestClient) -> None:
    resp = client.post(COMPARE_ROUTE, json=_payload(SUPPLIER_A, SUPPLIER_B))
    text = resp.text
    for forbidden in ("workspace_document_store", "claw_p01_adapter", "received_at", "P01", "B14"):
        assert forbidden not in text


class TestRouteSourceBoundary:
    """Mutation guards for the wiring itself, read off the AST not the prose.

    The handler docstring legitimately names the seams it must not touch, so a
    substring scan would match its own negations. These checks look at the
    compiled identifiers and call targets of that one function only.
    """

    HANDLER = "claw_manual_intake_quote_compare"

    def setup_method(self) -> None:
        self.source = (
            Path(__file__).resolve().parents[1] / "app" / "claw_routes.py"
        ).read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.handler = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == self.HANDLER
        )

    def _names(self, node: ast.AST | None = None) -> set[str]:
        names: set[str] = set()
        for sub in ast.walk(self.handler if node is None else node):
            if isinstance(sub, ast.Name):
                names.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                names.add(sub.attr)
            elif isinstance(sub, ast.keyword):
                names.add(sub.arg or "")
        return names

    def _awaited(self) -> set[str]:
        targets: set[str] = set()
        for node in ast.walk(self.handler):
            if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
                continue
            if isinstance(node.value.func, ast.Attribute):
                targets.add(node.value.func.attr)
            elif isinstance(node.value.func, ast.Name):
                targets.add(node.value.func.id)
        return targets

    def test_handler_uses_the_ops_engine_authority_not_a_local_copy(self) -> None:
        called = {
            node.func.id
            for node in ast.walk(self.handler)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert {"compare_supplier_quotes", "build_comparison_document"} <= called

    def test_handler_reaches_no_provider_quota_or_history_seam(self) -> None:
        assert self._names().isdisjoint(
            {
                "claw_p01_adapter",
                "create_claw_run",
                "P01CoreOrchestrationAdapter",
                "P01AdapterError",
                "P01DispatchClass",
                "_usage_gate_denial",
                "_refund_active_reservation",
                "_clear_reservation",
                "_record_claw_run_history",
                "_build_execute_task",
                "active_route_for",
                "ProductTierLabel",
                "ManualIntakeRouter",
                "execute",
                "dispatch",
                "send_negotiation",
                "OpsOutboundPort",
            }
        )

    def test_handler_reuses_the_existing_document_and_download_path(self) -> None:
        assert "build_document_artifact" in self._names()
        assert "put_generated_docx" in self._awaited()
        assert "_resolve_canonical_tenant" in self._awaited()
        # Same projection seam the execute route already uses: the stored
        # metadata object owns the public descriptor, never raw bytes.
        assert "public_projection" in self._names()
        assert "content_bytes" in self._names()
        execute = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "claw_manual_intake_execute"
        )
        assert {"build_document_artifact", "put_generated_docx", "public_projection"} <= self._names(
            execute
        )

    def test_registered_route_path_is_the_manual_intake_family(self) -> None:
        factory = (Path(__file__).resolve().parents[1] / "app" / "app_factory.py").read_text(
            encoding="utf-8"
        )
        assert factory.count('"/api/claw/manual-intake/quote-compare"') == 1
        assert "claw_manual_intake_quote_compare" in factory
        assert 'Route("/api/claw/manual-intake/preview", claw_manual_intake_preview, methods=["POST"])' in factory
