# Business 29 — minimal governance ledger backend (Phase 3A)

## SYNTHETIC DEVELOPMENT AUTHORITY ONLY
## NOT AUTHENTICATION
## MUST NOT BE ENABLED IN PRODUCTION

Local-only backend for the meeting-to-public-notice **governance ledger** (주민총회 원장)
of Business 29 · Apartment Governance / 우리단지 운영실.

Contract authorities: Issue #356 (backend architecture) · Phase 2 UX PR #352
(UX exact head `8e610bd040c6d48ba17fe087fd917be026c35cb2`, 34/34 non-browser validation).

## What this is / is not

```text
synthetic backend             — fixture-only, no real data
local-only                    — no production deployment
SQLite test database          — local dev/tests use SQLite
PostgreSQL-compatible design target — no SQLite-only SQL; Neon NOT provisioned
no real authentication        — synthetic actor headers only (NOT AUTHENTICATION)
no personal data              — no real resident/employee/vendor/litigation data
no production deployment      — no Neon/Modal provisioning
no legal judgement            — records are not legal advice
no real electronic voting     — no ballots, tallying, or election authority
no K-apt write integration    — no filing or write access to the national system
```

## Run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# tests (SQLite, no network, no DB accounts)
python -m pytest tests -q

# local server (SQLite)
uvicorn app.main:app --reload
# OpenAPI: http://127.0.0.1:8000/openapi.json
```

## Synthetic actor context (development only)

Every internal endpoint requires two headers:

```text
X-Synthetic-Actor: any-synthetic-name
X-Synthetic-Role:  admin | rep | office | auditor | resident | reviewer
```

Role slugs map to canonical roles:

```text
admin     → 대표회의 관리자
rep       → 동대표·위원
office    → 관리사무소
auditor   → 감사
resident  → 일반 주민
reviewer  → 외부 검토자
```

`일반 주민` may only read published `PublicProjection` via `GET /api/public/meetings/{id}`.

## Entities

20 tables (UUID PKs, timezone-aware UTC):

```text
Community, User, RoleAssignment, Meeting, Agenda, Rule, Notice, AttendanceRecord,
QuorumRecord, Discussion, Dissent, Resolution, ActionItem, Document, Redaction,
DisclosureReview, PublicProjection, Version, AuditEvent, IdempotencyRecord
```

## Domain flow

```text
meeting creation → agenda → notice draft → notice review → notice publication (Gate 1)
→ attendance open → quorum incomplete → attendance supplement → manual recheck
→ quorum recorded → discussion → dissent → resolution draft → review → approval
→ action item → disclosure review → redaction → disclosure approval → approved projection
→ final publication → published projection → completion | cancellation
```

Server-side guards:

```text
정족수 미달 상태에서 discussion/resolution 차단
quorum-incomplete → quorum-recorded 직접 전환 차단 (supplement + manual recheck 필수)
redaction 미완료 상태에서 disclosure 승인 차단 (REDACTION_INCOMPLETE)
외부 검토자가 아닌 actor의 disclosure 승인 차단
대표회의 관리자가 아닌 actor의 최종 게시 차단
검토 provenance 없는 projection 게시 차단
게시 전 raw object public 반환 금지
```

## Disclosure

```text
private raw → redaction → disclosure review → approved projection → final publication → published projection
GET /api/public/meetings/{id} returns ONLY published PublicProjection.
```

## Idempotency

Idempotent mutations require `idempotencyKey`: notice publication, attendance supplement,
quorum record, resolution approval, disclosure approval, final publication, meeting completion.
Same key + same request → stored response (no new Version/AuditEvent/projection).
Same key + different request → `409 IDEMPOTENCY_CONFLICT`.

## Audit

Every domain mutation writes exactly `1 Version + 1 AuditEvent` in the same transaction.
Disclosure approval writes `1 DisclosureReview + N PublicProjection + 1 Version + 1 AuditEvent`.
AuditEvent is append-only: no update/delete API exists.

## Errors

```text
400 VALIDATION · 403 ROLE_NOT_PERMITTED · 404 NOT_FOUND
409 IDEMPOTENCY_CONFLICT · 409 QUORUM_RECHECK_REQUIRED · 409 REDACTION_INCOMPLETE
409 DISCLOSURE_NOT_APPROVED · 409 PROJECTION_PROVENANCE_MISSING
413 BINARY_UPLOAD_NOT_ALLOWED · 422 INVALID_STATE_TRANSITION
```
