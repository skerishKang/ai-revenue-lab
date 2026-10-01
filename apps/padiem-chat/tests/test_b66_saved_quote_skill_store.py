"""Network-free tests for account-bound B66 Saved Quote Skill persistence (#3301)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.b66_saved_quote_skill_store import (
    MAX_SAVED_QUOTE_SKILLS,
    ApprovedSavedQuoteSkillArtifact,
    D1SavedQuoteSkillStore,
    SavedQuoteSkillStoreError,
    canonicalize_approved_artifact,
)


def _skill_payload(*, skill_id="saved-skill-1", name="우리 견적서", fingerprint="a" * 64):
    return {
        "schemaVersion": 1,
        "id": skill_id,
        "name": name,
        "fixedDefaults": {
            "sender": {
                "company": "테스트상사",
                "rep": "홍길동",
                "bizNo": "",
                "address": "",
                "phone": "",
                "email": "",
                "presetId": "saved-skill",
            },
            "validDays": 30,
            "taxMode": "EXCLUSIVE",
            "memo": "",
        },
        "variableSchema": {
            "recipient": True,
            "quoteNo": True,
            "issueDate": True,
            "items": True,
            "memo": True,
            "taxMode": True,
        },
        "internalTemplate": {"schemaVersion": 1, "id": "template-1"},
        "provenance": {
            "sourceKind": "manual",
            "sourceName": "",
            "sourceRef": "",
            "capturedAt": "",
            "warnings": [],
            "unknowns": [],
            "evidence": [],
        },
        "approval": {
            "schemaVersion": 1,
            "status": "approved",
            "skillFingerprint": fingerprint,
            "approvedBy": "operator:test",
            "approvedAt": "2026-10-01T00:00:00Z",
            "approvalRef": "manual:test",
        },
        "fingerprint": fingerprint,
        "rendererContract": "quote-template-renderer.v1",
        "calculationAuthority": "quote-core",
        "createdAt": "2026-10-01T00:00:00Z",
        "updatedAt": "2026-10-01T00:00:00Z",
    }


def _artifact(**overrides) -> ApprovedSavedQuoteSkillArtifact:
    skill_id = overrides.pop("skill_id", "saved-skill-1")
    name = overrides.pop("skill_name", "우리 견적서")
    fingerprint = overrides.pop("fingerprint", "a" * 64)
    version = overrides.pop("version", 1)
    payload = overrides.pop(
        "payload",
        _skill_payload(skill_id=skill_id, name=name, fingerprint=fingerprint),
    )
    assert not overrides
    return canonicalize_approved_artifact(
        skill_id=skill_id,
        skill_name=name,
        fingerprint=fingerprint,
        version=version,
        serialized_json=json.dumps(payload, ensure_ascii=False),
    )


def test_canonicalize_accepts_bounded_approved_envelope() -> None:
    artifact = _artifact()
    assert artifact.skill_id == "saved-skill-1"
    assert artifact.skill_name == "우리 견적서"
    assert artifact.fingerprint == "a" * 64
    assert artifact.version == 1
    parsed = json.loads(artifact.serialized_json)
    assert parsed["approval"]["status"] == "approved"
    assert parsed["rendererContract"] == "quote-template-renderer.v1"
    assert parsed["calculationAuthority"] == "quote-core"


@pytest.mark.parametrize(
    ("mutator", "code_fragment"),
    [
        (lambda p: p.update(approval=None), "not approved"),
        (
            lambda p: p["approval"].update(skillFingerprint="b" * 64),
            "approval fingerprint mismatch",
        ),
        (lambda p: p.update(fingerprint="b" * 64), "fingerprint mismatch"),
        (lambda p: p.update(id="other-skill"), "id mismatch"),
        (lambda p: p.update(name="다른 이름"), "name mismatch"),
        (
            lambda p: p.update(rendererContract="other-renderer"),
            "renderer contract mismatch",
        ),
        (
            lambda p: p.update(calculationAuthority="browser-math"),
            "calculation authority mismatch",
        ),
    ],
)
def test_unapproved_or_mismatched_envelope_fails_closed(mutator, code_fragment) -> None:
    payload = _skill_payload()
    mutator(payload)
    with pytest.raises(SavedQuoteSkillStoreError, match=code_fragment):
        canonicalize_approved_artifact(
            skill_id="saved-skill-1",
            skill_name="우리 견적서",
            fingerprint="a" * 64,
            version=1,
            serialized_json=json.dumps(payload, ensure_ascii=False),
        )


def test_oversized_and_invalid_artifacts_fail_closed() -> None:
    with pytest.raises(SavedQuoteSkillStoreError, match="skill_id"):
        canonicalize_approved_artifact(
            skill_id="../evil",
            skill_name="우리 견적서",
            fingerprint="a" * 64,
            version=1,
            serialized_json="{}",
        )
    with pytest.raises(SavedQuoteSkillStoreError, match="skill_fingerprint"):
        canonicalize_approved_artifact(
            skill_id="saved-skill-1",
            skill_name="우리 견적서",
            fingerprint="not-a-fingerprint",
            version=1,
            serialized_json="{}",
        )
    with pytest.raises(SavedQuoteSkillStoreError, match="skill_version"):
        canonicalize_approved_artifact(
            skill_id="saved-skill-1",
            skill_name="우리 견적서",
            fingerprint="a" * 64,
            version=0,
            serialized_json="{}",
        )


class _Statement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql
        self.values = ()

    def bind(self, *values):
        self.values = values
        self.db.bound.append((self.sql, values))
        return self

    async def first(self):
        if self.sql.startswith("SELECT id FROM b66_saved_quote_skill"):
            if len(self.values) == 4:
                user_id, workspace_id, skill_id, version = self.values
                for row in self.db.rows:
                    if (
                        row["user_id"] == user_id
                        and row["workspace_id"] == workspace_id
                        and row["skill_id"] == skill_id
                        and row["skill_version"] == version
                    ):
                        return {"id": row["id"]}
                return None
            row_id, user_id, workspace_id = self.values
            for row in self.db.rows:
                if (
                    row["id"] == row_id
                    and row["user_id"] == user_id
                    and row["workspace_id"] == workspace_id
                    and row["status"] == "approved"
                ):
                    return {"id": row["id"]}
            return None

        if self.sql.startswith(
            "SELECT id, workspace_id, skill_id, skill_name, skill_fingerprint"
        ):
            row_id, user_id, workspace_id = self.values
            for row in self.db.rows:
                if (
                    row["id"] == row_id
                    and row["user_id"] == user_id
                    and row["workspace_id"] == workspace_id
                    and ("status='approved'" not in self.sql or row["status"] == "approved")
                ):
                    return {
                        k: v
                        for k, v in row.items()
                        if k != "user_id"
                    }
            return None
        return None

    async def run(self):
        if self.sql.startswith("INSERT INTO b66_saved_quote_skill"):
            (
                row_id,
                user_id,
                workspace_id,
                skill_id,
                skill_name,
                fingerprint,
                version,
                skill_json,
                created_at,
                updated_at,
            ) = self.values
            self.db.rows.append(
                {
                    "id": row_id,
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "skill_fingerprint": fingerprint,
                    "skill_version": version,
                    "skill_json": skill_json,
                    "status": "approved",
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
            return {"results": []}

        if self.sql.startswith("UPDATE b66_saved_quote_skill SET skill_name"):
            (
                skill_name,
                fingerprint,
                skill_json,
                updated_at,
                row_id,
                user_id,
                workspace_id,
            ) = self.values
            for row in self.db.rows:
                if (
                    row["id"] == row_id
                    and row["user_id"] == user_id
                    and row["workspace_id"] == workspace_id
                ):
                    row.update(
                        skill_name=skill_name,
                        skill_fingerprint=fingerprint,
                        skill_json=skill_json,
                        status="approved",
                        updated_at=updated_at,
                    )
            return {"results": []}

        if self.sql.startswith("UPDATE b66_saved_quote_skill SET status='disabled'"):
            updated_at, row_id, user_id, workspace_id = self.values
            for row in self.db.rows:
                if (
                    row["id"] == row_id
                    and row["user_id"] == user_id
                    and row["workspace_id"] == workspace_id
                    and row["status"] == "approved"
                ):
                    row["status"] = "disabled"
                    row["updated_at"] = updated_at
            return {"results": []}

        if self.sql.startswith(
            "SELECT id, workspace_id, skill_id, skill_name, skill_fingerprint"
        ):
            user_id, workspace_id, limit = self.values
            rows = [
                row
                for row in self.db.rows
                if row["user_id"] == user_id
                and row["workspace_id"] == workspace_id
                and row["status"] == "approved"
            ]
            rows.sort(key=lambda row: row["updated_at"], reverse=True)
            return {
                "results": [
                    {k: v for k, v in row.items() if k not in {"user_id", "skill_json"}}
                    for row in rows[:limit]
                ]
            }

        return {"results": []}


class _D1:
    def __init__(self):
        self.rows = []
        self.prepared = []
        self.bound = []

    def prepare(self, sql):
        self.prepared.append(sql)
        return _Statement(self, sql)


@pytest.mark.asyncio
async def test_d1_store_is_owner_workspace_scoped_and_nondisclosing() -> None:
    db = _D1()
    store = D1SavedQuoteSkillStore(db)
    created = await store.put_approved_skill(
        user_id="usr_owner",
        workspace_id="ws_one",
        artifact=_artifact(),
    )
    assert created["saved_skill_id"].startswith("b66skill_")
    assert created["skill"]["fingerprint"] == "a" * 64

    own = await store.list_skills(
        user_id="usr_owner",
        workspace_id="ws_one",
        limit=999,
    )
    assert len(own) == 1
    assert "skill" not in own[0]
    assert len(own) <= MAX_SAVED_QUOTE_SKILLS

    detail = await store.get_skill(
        user_id="usr_owner",
        workspace_id="ws_one",
        saved_skill_id=created["saved_skill_id"],
    )
    assert detail is not None
    assert detail["skill_id"] == "saved-skill-1"

    assert (
        await store.get_skill(
            user_id="usr_other",
            workspace_id="ws_one",
            saved_skill_id=created["saved_skill_id"],
        )
        is None
    )
    assert (
        await store.get_skill(
            user_id="usr_owner",
            workspace_id="ws_other",
            saved_skill_id=created["saved_skill_id"],
        )
        is None
    )

    # Dynamic ownership values are always statement binds, never SQL text.
    assert all("usr_owner" not in sql and "ws_one" not in sql for sql in db.prepared)


@pytest.mark.asyncio
async def test_disable_is_owner_scoped_and_removes_active_projection() -> None:
    store = D1SavedQuoteSkillStore(_D1())
    created = await store.put_approved_skill(
        user_id="usr_owner",
        workspace_id="ws_one",
        artifact=_artifact(),
    )
    saved_id = created["saved_skill_id"]

    assert (
        await store.disable_skill(
            user_id="usr_other",
            workspace_id="ws_one",
            saved_skill_id=saved_id,
        )
        is False
    )
    assert (
        await store.disable_skill(
            user_id="usr_owner",
            workspace_id="ws_one",
            saved_skill_id=saved_id,
        )
        is True
    )
    assert (
        await store.get_skill(
            user_id="usr_owner",
            workspace_id="ws_one",
            saved_skill_id=saved_id,
        )
        is None
    )
    assert (
        await store.list_skills(
            user_id="usr_owner",
            workspace_id="ws_one",
        )
        == []
    )


@pytest.mark.asyncio
async def test_same_version_updates_only_same_owner_workspace_record() -> None:
    store = D1SavedQuoteSkillStore(_D1())
    first = await store.put_approved_skill(
        user_id="usr_owner",
        workspace_id="ws_one",
        artifact=_artifact(),
    )
    changed_payload = _skill_payload(name="수정된 견적서")
    changed_payload["approval"]["skillFingerprint"] = "a" * 64
    changed = _artifact(skill_name="수정된 견적서", payload=changed_payload)
    second = await store.put_approved_skill(
        user_id="usr_owner",
        workspace_id="ws_one",
        artifact=changed,
    )
    assert first["saved_skill_id"] == second["saved_skill_id"]
    assert second["skill_name"] == "수정된 견적서"


def test_migration_021_is_additive_and_contains_no_raw_source_columns() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "021_b66_saved_quote_skill.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b66_saved_quote_skill" in migration
    assert "user_id TEXT NOT NULL REFERENCES users(id)" in migration
    assert "workspace_id TEXT NOT NULL" in migration
    assert "skill_fingerprint TEXT NOT NULL" in migration
    assert "skill_json TEXT NOT NULL" in migration
    assert "status IN ('approved', 'disabled')" in migration
    for forbidden in (
        "raw_source",
        "source_bytes",
        "file_bytes",
        "base64",
        "oauth_token",
        "access_token",
        "provider_payload",
    ):
        assert forbidden not in migration.lower()


def test_store_has_no_runtime_ddl_or_second_quote_authority() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "b66_saved_quote_skill_store.py"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source
    assert "QuoteCore" not in source
    assert "normalizeTemplate" not in source
    assert "buildDraft" not in source
    assert "provider" not in source.lower()
    assert "model" not in source.lower()
