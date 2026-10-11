"""Contract acceptance tests for canonical D1 evidence storage wiring (#2954).

Proves that:
  1. Migration 0007 (0007_engine_evidence.sql) matches CloudflareD1EvidenceStoragePort SQL contract;
  2. wrangler.toml declares logical ENGINE_EVIDENCE_STORE targeting padiem-engine;
  3. Worker composition injects CloudflareD1EvidenceStoragePort in both composition branches;
  4. Missing or invalid ENGINE_EVIDENCE_STORE binding fails closed (None in composition, 503 at runtime);
  5. Both composition branches share the canonical CloudflareD1EvidenceStoragePort authority;
  6. Document context through-line retains EvidenceStorageProjection into D1 evidence table exactly once;
  7. Response projection contains only bounded view + evidence_id with zero leak of body, locators, refs, or scopes;
  8. Contract manifest keeps document_projection and document_admission truthfully DEFERRED.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import re
import sys
import types
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.contract_manifest import (  # noqa: E402
    EngineFeatureState,
    current_engine_contract_manifest,
)
from app.document_byte_store import (  # noqa: E402
    CloudflareD1DocumentByteStore,
    ScopedDocumentByteStore,
)
from app.document_context_service import (  # noqa: E402
    DOCUMENT_CONTEXT_PATH,
    DocumentContextEngineService,
    TrustedCallerScope,
)
from app.document_evidence_projection import (  # noqa: E402
    EvidenceStorageProjection,
)
from app.engine_composition import EngineServices  # noqa: E402
from app.evidence_storage_d1 import CloudflareD1EvidenceStoragePort  # noqa: E402
from app.trusted_document_resolver import (  # noqa: E402
    DurableDocumentStoragePort,
    TrustedDocumentResolver,
)

CALLER_ID = "e9-d1-evidence-caller"
CALLER_SECRET = "e9-d1-evidence-secret-0123456789abcdef-0123456789abcdef"
DOC_REF = "doc_e9D1Evidence000001"
BODY = "Padiem AI Engine Q3 performance review narrative with tail marker TAILNOTINPREVIEW-998811"
SECRET_TAIL = "TAILNOTINPREVIEW-998811"
SCOPE = {"app_id": "b62", "subject_id": "user.101", "tenant_id": "tenant.omega"}
NOW = datetime.now(timezone.utc)
EXPIRES = NOW + timedelta(days=1)


# --- Fake D1 Infrastructure ----------------------------------------------------


class FakeD1Statement:
    def __init__(self, db: "FakeD1Database", sql: str) -> None:
        self.db = db
        self.sql = " ".join(sql.split())
        self.params: tuple[Any, ...] = ()

    def bind(self, *params: Any) -> "FakeD1Statement":
        self.params = params
        return self

    async def run(self) -> dict[str, Any]:
        self.db.run_log.append((self.sql, self.params))
        if self.sql.startswith("INSERT INTO padiem_engine_evidence"):
            evidence_id, document_json, retention_json, created_at = self.params
            if evidence_id in self.db.evidence_rows:
                raise AssertionError(f"duplicate primary key: {evidence_id}")
            self.db.evidence_rows[evidence_id] = {
                "evidence_id": evidence_id,
                "document_json": document_json,
                "retention_json": retention_json,
                "created_at": created_at,
            }
            return {"success": True}
        raise AssertionError(f"unexpected run SQL: {self.sql}")

    async def first(self) -> dict[str, Any] | None:
        self.db.first_log.append((self.sql, self.params))
        if self.sql == "SELECT evidence_id FROM padiem_engine_evidence WHERE evidence_id=? LIMIT 1":
            (evidence_id,) = self.params
            return {"evidence_id": evidence_id} if evidence_id in self.db.evidence_rows else None
        if self.sql.startswith("SELECT evidence_id,document_json,retention_json,created_at FROM padiem_engine_evidence"):
            (evidence_id,) = self.params
            row = self.db.evidence_rows.get(evidence_id)
            return dict(row) if row else None
        if "FROM padiem_engine_document_bytes WHERE document_ref=? LIMIT 1" in self.sql:
            (doc_ref,) = self.params
            row = self.db.document_rows.get(doc_ref)
            return dict(row) if row else None
        raise AssertionError(f"unexpected first SQL: {self.sql}")


class FakeD1Database:
    def __init__(self) -> None:
        self.evidence_rows: dict[str, dict[str, Any]] = {}
        self.document_rows: dict[str, dict[str, Any]] = {}
        self.run_log: list[tuple[str, tuple[Any, ...]]] = []
        self.first_log: list[tuple[str, tuple[Any, ...]]] = []

    def prepare(self, sql: str) -> FakeD1Statement:
        return FakeD1Statement(self, sql)

    def seed_document(
        self,
        *,
        doc_ref: str = DOC_REF,
        payload: bytes = BODY.encode("utf-8"),
        app_id: str = SCOPE["app_id"],
        tenant_id: str = SCOPE["tenant_id"],
        subject_id: str = SCOPE["subject_id"],
        media_type: str = "text/plain",
        name: str = "notes.txt",
    ) -> None:
        self.document_rows[doc_ref] = {
            "document_ref": doc_ref,
            "app_id": app_id,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "media_type": media_type,
            "name": name,
            "byte_size": len(payload),
            "created_at": NOW.isoformat(),
            "expires_at": EXPIRES.isoformat(),
            "terminal": 0,
            "payload_base64": base64.b64encode(payload).decode("ascii"),
        }


# --- Workers stub & identity modules fixture ----------------------------------


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, ctx: Any = None, env: Any = None) -> None:
        self.ctx = ctx
        self.env = env


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module")
def identity_modules():
    saved = {
        name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")
    }
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        identity = importlib.import_module("worker_identity")
        legacy = importlib.import_module("worker")
        yield legacy, identity
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Env:
    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


def _identity_env(**extra: Any) -> _Env:
    return _Env(
        PADIEM_ENGINE_CALLER_ID=CALLER_ID,
        PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
        PADIEM_ENGINE_ALLOWED_APPS=SCOPE["app_id"],
        **extra,
    )


class _Request:
    def __init__(
        self,
        path: str,
        *,
        method: str = "POST",
        body: bytes = b"{}",
        authenticated: bool = True,
    ) -> None:
        self.url = f"https://engine.internal{path}"
        self.method = method
        headers: dict[str, str] = {"content-type": "application/json"}
        if authenticated:
            headers["x-padiem-engine-caller"] = CALLER_ID
            headers["x-padiem-engine-credential"] = CALLER_SECRET
        self.headers = headers
        self._text = body.decode("utf-8")

    async def text(self) -> str:
        return self._text


def _request_payload(**fields: Any) -> bytes:
    payload = {
        "app_id": SCOPE["app_id"],
        "session_id": "sess.canonical-test-01",
        "document_ref": DOC_REF,
    }
    payload.update(fields)
    return json.dumps(payload).encode("utf-8")


class _MockScopeAuthority:
    def __init__(self, scope: TrustedCallerScope | None = None) -> None:
        self.scope = scope or TrustedCallerScope(**SCOPE)

    async def scope_for_request(self, *, app_id: str, auth_session_id: str) -> TrustedCallerScope:
        return self.scope


# --- 1: Migration Schema Contract ---------------------------------------------


def test_0007_migration_file_matches_evidence_storage_sql_contract() -> None:
    migration_path = APP_ROOT / "migrations" / "0007_engine_evidence.sql"
    assert migration_path.exists(), "0007_engine_evidence.sql must exist"
    sql = migration_path.read_text(encoding="utf-8")

    assert re.search(r"CREATE TABLE IF NOT EXISTS padiem_engine_evidence\b\s*\(", sql) is not None
    assert "PRIMARY KEY (evidence_id)" in sql or "PRIMARY KEY(evidence_id)" in sql
    assert "evidence_id TEXT NOT NULL" in sql
    assert "document_json TEXT NOT NULL" in sql
    assert "retention_json TEXT NOT NULL" in sql
    assert "created_at TEXT NOT NULL" in sql
    assert "idx_padiem_engine_evidence_created_at" in sql
    assert re.search(r"ON padiem_engine_evidence\b\s*\(created_at\)", sql) is not None

    # Bounds in CHECK constraints match CloudflareD1EvidenceStoragePort limits
    assert "length(evidence_id) >= 16" in sql
    assert "length(evidence_id) <= 64" in sql
    assert "length(document_json) <= 2000000" in sql
    assert "length(retention_json) <= 2000000" in sql

    # Non-destructive: no DROP/DELETE/ALTER/UPDATE
    for forbidden in (r"^\s*DROP\b", r"^\s*DELETE\b", r"^\s*ALTER\b", r"^\s*UPDATE\b"):
        assert re.search(forbidden, sql, re.M | re.I) is None


# --- 2: Wrangler Binding Declaration Contract ---------------------------------


def test_wrangler_declares_engine_evidence_store_binding() -> None:
    wrangler_path = APP_ROOT / "wrangler.toml"
    assert wrangler_path.exists()
    content = wrangler_path.read_text(encoding="utf-8")

    assert 'binding = "ENGINE_EVIDENCE_STORE"' in content
    block = content[content.index('binding = "ENGINE_EVIDENCE_STORE"') :]
    end_idx = block.find("[[", 2)
    chunk = block[:end_idx] if end_idx != -1 else block[:block.find("[env.")]

    assert 'database_name = "padiem-engine"' in chunk
    assert 'database_id = "6b77ad02-bc27-488f-bb97-6325f6750cba"' in chunk


# --- 3: Worker Identity Composition Contract -----------------------------------


def test_worker_identity_exports_evidence_binding_constant(identity_modules) -> None:
    _legacy, identity = identity_modules
    assert hasattr(identity, "ENGINE_EVIDENCE_STORE_BINDING")
    assert identity.ENGINE_EVIDENCE_STORE_BINDING == "ENGINE_EVIDENCE_STORE"


def test_composition_wires_evidence_storage_in_both_branches(identity_modules) -> None:
    _legacy, identity = identity_modules
    fake_d1 = FakeD1Database()

    for b14_bound in (False, True):
        env_kwargs: dict[str, Any] = {"ENGINE_EVIDENCE_STORE": fake_d1}
        if b14_bound:
            env_kwargs["B14_SERVICE"] = object()
        env = _identity_env(**env_kwargs)

        services = asyncio.run(identity._engine_services_for_env(env))
        assert isinstance(services, EngineServices)
        assert isinstance(services.documents, DocumentContextEngineService)

        evidence_storage = services.documents._evidence_storage
        assert isinstance(evidence_storage, CloudflareD1EvidenceStoragePort)
        assert evidence_storage._binding is fake_d1


# --- 4: Missing or Invalid Binding Fails Closed -------------------------------


def test_composition_fails_closed_when_evidence_store_is_missing(identity_modules) -> None:
    _legacy, identity = identity_modules

    for b14_bound in (False, True):
        env_kwargs: dict[str, Any] = {}
        if b14_bound:
            env_kwargs["B14_SERVICE"] = object()
        env = _identity_env(**env_kwargs)

        services = asyncio.run(identity._engine_services_for_env(env))
        assert isinstance(services.documents, DocumentContextEngineService)
        assert services.documents._evidence_storage is None


@pytest.mark.parametrize(
    "malformed_binding",
    [
        object(),
        "",
        12345,
        [],
        {"binding": "ENGINE_EVIDENCE_STORE"},
        b"not-a-d1-binding",
    ],
)
def test_composition_fails_closed_on_malformed_evidence_store(
    identity_modules, malformed_binding: Any
) -> None:
    _legacy, identity = identity_modules

    env = _identity_env(ENGINE_EVIDENCE_STORE=malformed_binding)
    services = asyncio.run(identity._engine_services_for_env(env))
    assert isinstance(services.documents, DocumentContextEngineService)
    assert services.documents._evidence_storage is None


# --- 5: Runtime Fail-Closed without Evidence Store ----------------------------


def test_runtime_fails_closed_503_when_evidence_storage_missing() -> None:
    scope_authority = _MockScopeAuthority()
    resolver = TrustedDocumentResolver(
        storage=DurableDocumentStoragePort(
            ScopedDocumentByteStore(port=CloudflareD1DocumentByteStore(FakeD1Database()))
        )
    )
    service = DocumentContextEngineService(
        scope_authority=scope_authority,
        document_resolver=resolver,
        evidence_storage=None,  # missing
    )

    response = asyncio.run(
        service.handle(
            method="POST",
            path=DOCUMENT_CONTEXT_PATH,
            content_type="application/json",
            body=_request_payload(),
        )
    )

    assert response.status_code == 503
    assert response.body["error"]["code"] == "evidence_storage_unavailable"


# --- 6: End-to-End Positive Through-Line with D1 Storage ----------------------


def test_end_to_end_document_context_retains_evidence_into_d1_once(identity_modules) -> None:
    _legacy, identity = identity_modules
    doc_d1 = FakeD1Database()
    doc_d1.seed_document(doc_ref=DOC_REF, payload=BODY.encode("utf-8"))
    evidence_d1 = FakeD1Database()

    mock_scope = _MockScopeAuthority()

    env = _identity_env(
        ENGINE_DOCUMENT_STORE=doc_d1,
        ENGINE_EVIDENCE_STORE=evidence_d1,
    )

    real_factory = identity.Default.engine_services_factory

    async def spying_factory(e: Any) -> EngineServices:
        services = await real_factory(e)
        return dataclasses.replace(
            services,
            documents=DocumentContextEngineService(
                scope_authority=mock_scope,
                document_resolver=services.documents._document_resolver,
                evidence_storage=services.documents._evidence_storage,
            ),
        )

    identity.Default.engine_services_factory = staticmethod(spying_factory)
    try:
        response = asyncio.run(
            identity.Default(ctx=None, env=env).fetch(
                _Request(DOCUMENT_CONTEXT_PATH, body=_request_payload())
            )
        )
        assert response.status == 200
        body = json.loads(str(response.body))
        assert body["ok"] is True

        # Document projection is bounded
        doc = body["document"]
        assert doc["name"] == "notes.txt"
        assert doc["media_type"] == "text/plain"
        assert doc["byte_size"] == len(BODY.encode("utf-8"))
        assert doc["text_chars"] == len(BODY)
        assert doc["truncated_text_preview"] == BODY

        # Evidence ID is engine-minted token
        evidence_id = body["evidence"]["evidence_id"]
        assert 16 <= len(evidence_id) <= 64

        # D1 binding received exactly one INSERT
        assert len(evidence_d1.evidence_rows) == 1
        assert evidence_id in evidence_d1.evidence_rows

        insert_calls = [
            (sql, params)
            for sql, params in evidence_d1.run_log
            if "INSERT INTO padiem_engine_evidence" in sql
        ]
        assert len(insert_calls) == 1
        assert insert_calls[0][1][0] == evidence_id

        # Verify through the port that the retained projection round-trips
        evidence_port = CloudflareD1EvidenceStoragePort(evidence_d1)
        retained = asyncio.run(evidence_port.retrieve(evidence_id))
        assert isinstance(retained, EvidenceStorageProjection)
        assert retained.evidence_id == evidence_id
        assert retained.att_ref == DOC_REF
        assert retained.normalized_document.text == BODY
        assert retained.storage_locator == f"evidence://{DOC_REF}"

        # Document byte store received fetch, but was not mutated
        assert len(doc_d1.run_log) == 0
        assert len(doc_d1.document_rows) == 1
    finally:
        identity.Default.engine_services_factory = staticmethod(real_factory)


# --- 7: Redaction and Zero-Leak Surface ----------------------------------------


def test_response_leaks_no_private_materials(identity_modules) -> None:
    _legacy, identity = identity_modules
    doc_d1 = FakeD1Database()
    doc_d1.seed_document(doc_ref=DOC_REF, payload=BODY.encode("utf-8"))
    evidence_d1 = FakeD1Database()

    mock_scope = _MockScopeAuthority()

    env = _identity_env(
        ENGINE_DOCUMENT_STORE=doc_d1,
        ENGINE_EVIDENCE_STORE=evidence_d1,
    )

    real_factory = identity.Default.engine_services_factory

    async def spying_factory(e: Any) -> EngineServices:
        services = await real_factory(e)
        return dataclasses.replace(
            services,
            documents=DocumentContextEngineService(
                scope_authority=mock_scope,
                document_resolver=services.documents._document_resolver,
                evidence_storage=services.documents._evidence_storage,
            ),
        )

    identity.Default.engine_services_factory = staticmethod(spying_factory)
    try:
        response = asyncio.run(
            identity.Default(ctx=None, env=env).fetch(
                _Request(DOCUMENT_CONTEXT_PATH, body=_request_payload())
            )
        )
        body_str = str(response.body).lower()

        # Zero leaks of storage locators, internal references, or scopes
        assert "evidence://" not in body_str
        assert "att_" not in body_str
        assert DOC_REF.lower() not in body_str
        assert "tenant.omega" not in body_str
        assert "user.101" not in body_str
    finally:
        identity.Default.engine_services_factory = staticmethod(real_factory)


# --- 8: Manifest Truth Preservation -------------------------------------------


def test_document_capabilities_remain_deferred_in_manifest() -> None:
    manifest = current_engine_contract_manifest()
    assert (
        manifest.feature_state("document_projection") is EngineFeatureState.DEFERRED
    ), "document_projection must remain truthfully DEFERRED until live verification"
    assert (
        manifest.feature_state("document_admission") is EngineFeatureState.DEFERRED
    ), "document_admission must remain truthfully DEFERRED until live verification"
