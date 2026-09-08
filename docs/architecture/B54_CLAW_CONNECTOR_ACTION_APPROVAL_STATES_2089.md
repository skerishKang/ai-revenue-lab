# B54 Claw Connector/Action Approval States (#2089)

- Status: DRAFT — ACT-0 read-only audit record; no implementation authorised by this document
- Issue: #2089 — [B54/B62][Connector UX] Audit disabled Claw connector/action controls and define approval-gated next states
- Scope: Classification of nine user-visible Claw actions into exact current state and approval-gated next state
- Collision Boundary: `apps/padiem-chat/**` is untouched by this document (reserved for ZCODE/B62); `apps/korean-ai-code-agent/**` is B54-owned source of the safety contract
- Audited at: `a410b7224c9910e205306e8fd6e8694b10aaf40a`

---

## 1. Executive Summary

This document records the ACT-0 read-only audit of the Claw connector/action surface
and defines the exact approval-gated next state for each of nine user-visible actions.

Audit verdict:

```text
OVERCLAIM_RISK_FOUND        = NO
UNSAFE_ENABLED_ACTION_FOUND = NO
```

Rationale: the only enabled Claw action is 초안 만들기 (create preview), which is
read-only and explicitly labelled. Five further actions are rendered as inert
disabled controls. The remaining three connector-backed actions plus automation have
no control in the Claw surface at all.

This document is a **state definition only**. It authorises no code change, no
endpoint, no connector grant, and no storage mutation.

---

## 2. Audited Source Surfaces

Read-only audit only. No file below was modified by this issue.

| Layer | Path | Relevance |
|---|---|---|
| Claw UI shell | `apps/padiem-chat/static/index.html` | `#clawDialog`, `.claw-disabled-controls` (lines 159-180) |
| Claw UI logic | `apps/padiem-chat/static/app.js` | preview fetch only (lines 1146-1277) |
| Copy (ko/en) | `apps/padiem-chat/static/locale.js` | `claw-ctrl-*` (lines 24-28 ko, 67-71 en) |
| Disabled styling | `apps/padiem-chat/static/claw-manual-intake.css` | `.claw-disabled-control` (line 91) |
| Route table | `apps/padiem-chat/app/app_factory.py` | single Claw route (line 90) |
| Safety contract | `apps/korean-ai-code-agent/src/kagent/manual_intake.py` | `ManualIntakeSafetyDecision` (line 76), `ManualIntakeDisabledAction` (line 100) |
| Export capability | `apps/korean-ai-code-agent/src/kagent/document_export.py` | `generate_docx_bytes` (line 91), `export_outcome_to_file` (line 169) |
| Memory capability | `apps/korean-ai-code-agent/src/kagent/claw_memory.py` | `ClawMemoryStore` (line 701), `InMemoryClawMemoryStore` (line 729) |
| Automation capability | `apps/korean-ai-code-agent/src/kagent/claw_automation.py` | `InMemoryClawAutomationStore` (line 284), `FakeClawScheduler` (line 317) |

---

## 3. `ManualIntakeSafetyDecision` Invariants (existing, source of truth)

Defined in `apps/korean-ai-code-agent/src/kagent/manual_intake.py`. The first five
fields are enforced in `__post_init__` and raise `ContractError` on drift. The last
three are declared contract fields.

```text
connector_required                   = False   (enforced — must stay False)
raw_input_trusted_as_memory          = False   (enforced — must stay False)
memory_update_requires_user_approval = True    (enforced — must stay True)
direct_kakao_send_allowed            = False   (enforced — must stay False)
direct_sms_send_allowed              = False   (enforced — must stay False)
email_send_requires_user_approval    = True
share_link_requires_storage_2055     = True
google_drive_save_requires_connector = True
```

Runtime boundary: `ManualIntakeResult.safe_dict()` always reports
`direct_kakao_send=False` and `direct_sms_send=False` to the client regardless of
input, and redacts `result_text` through `redact_secrets()`.

Consequence for this document: no row in the state table below may be promoted to a
live state in a way that violates any field above. Kakao and SMS direct send are
permanently forbidden, not merely deferred.

---

## 4. Endpoint Reality

Exactly one Claw endpoint is routed at the audited head:

```text
POST /api/claw/manual-intake/preview
```

No endpoint exists for markdown download, DOCX download, memory save, email send,
share link, Google Drive save, Gmail read/import, Gmail send, or automation dispatch.

### Capability versus endpoint distinction

`document_export.py` already generates `md` and `docx` payloads
(`generate_docx_bytes`, `SUPPORTED_DOCUMENT_FORMATS = ("md", "docx", "hwpx")`).
Only the HTTP endpoint is absent. Therefore the UI note "백엔드 연결 전까지 비활성화"
must be read as *endpoint* wiring missing, not *generation* capability missing.
This distinction is recorded here to prevent premature enablement.

`hwpx` is a documented deferral and `hwp` is an explicit non-goal; both raise
`DocumentExportError` (see `B54_CLAW_DOCUMENT_EXPORT_2016.md`).

---

## 5. Nine-Action State Table

### Group A — control exists in the Claw UI (5)

All five are rendered as
`<button type="button" class="claw-disabled-control" disabled aria-disabled="true">`
inside `#clawDialog`. None carries an `id`, and no event listener is bound to
`.claw-disabled-control` in any `apps/padiem-chat/static/*.js` file — the controls
are inert, not merely visually dimmed. CSS applies `cursor: not-allowed` and
`opacity: 0.7`, so the state is **visible disabled**.

| # | Action | CURRENT_UI_STATE | NEXT_ALLOWED_STATE | REQUIRES_USER_APPROVAL | REQUIRES_CONNECTOR_GRANT | REQUIRES_STORAGE | REQUIRES_BACKEND_ENDPOINT | SAFE_COPY |
|---|---|---|---|---|---|---|---|---|
| 1 | Markdown download | visible disabled | approval-gated → live-after-backend | NO | NO | NO (stream in memory) | YES (absent) | keep "백엔드 연결 전까지 비활성화"; add "미리보기 내용만 내보냅니다" when promoted |
| 2 | DOCX download | visible disabled | approval-gated → live-after-backend | NO | NO | NO (stream in memory) | YES (absent) | same as #1 |
| 3 | Memory save proposal | visible disabled | approval-gated — never auto-write | YES (contract-enforced) | NO | YES (none today) | YES (absent) | keep "사용자 승인 필요 / 준비 중" |
| 4 | Email send | visible disabled | approval-gated → live-after-connector | YES (contract-enforced) | YES | NO | YES (absent) | keep "사용자 승인 필요 / 준비 중" |
| 5 | Share link | visible disabled | live-after-storage (#2055) | NO | NO | YES | YES (absent) | keep "저장소 연결 후 가능" |

### Group B — no control exists in the Claw UI (4)

| # | Action | CURRENT_UI_STATE | NEXT_ALLOWED_STATE | REQUIRES_USER_APPROVAL | REQUIRES_CONNECTOR_GRANT | REQUIRES_STORAGE | REQUIRES_BACKEND_ENDPOINT | SAFE_COPY |
|---|---|---|---|---|---|---|---|---|
| 6 | Google Drive save | hidden / unavailable — only a non-interactive "준비 중" card in the (itself disabled) Connectors dialog | live-after-connector | YES | YES | NO | YES (absent) | none required until a control is introduced |
| 7 | Gmail read/import | hidden / unavailable — same card form | live-after-connector; imported content may only become a memory proposal | YES | YES | YES | YES (absent) | none required |
| 8 | Gmail send | hidden — no control anywhere in the Claw surface | live-after-connector + approval | YES | YES | NO | YES (absent) | none required |
| 9 | Follow-up task / automation | hidden — no Claw control (`#tasksNavButton` is generic workspace nav, unrelated to Claw) | approval-gated; no dispatch without a real scheduler | YES | NO | YES | YES (absent) | none required |

Notes on Group B:

- Google Drive and Gmail appear in `index.html` (lines 190-191) as
  `<div class="capability-card">` elements with a `<span class="capability-soon">준비 중</span>`
  badge. They are not `<button>` elements and carry no handler.
- `claw_automation.py` ships only `InMemoryClawAutomationStore` and
  `FakeClawScheduler`, the latter documented as "Deterministic fake scheduler for
  unit testing and local checks". There is no production scheduler, so action #9
  must never be promoted to a dispatching state without one.
- `claw_memory.py` documents `InMemoryClawMemoryStore` as having "No production
  persistence". Action #3 therefore cannot become durable without a real store.

---

## 6. Promotion Gate Rules

A row may move from its `CURRENT_UI_STATE` to its `NEXT_ALLOWED_STATE` only when all
of the following hold:

```text
CONTRACT_INVARIANTS_INTACT          = YES   (section 3 fields unchanged)
REQUIRED_ENDPOINT_PRESENT           = YES   (REQUIRES_BACKEND_ENDPOINT column)
REQUIRED_STORAGE_PRESENT            = YES   (REQUIRES_STORAGE column, where YES)
REQUIRED_CONNECTOR_GRANT_PRESENT    = YES   (REQUIRES_CONNECTOR_GRANT column, where YES)
USER_APPROVAL_PATH_IMPLEMENTED      = YES   (REQUIRES_USER_APPROVAL column, where YES)
EXISTING_DISABLED_STATE_TEST_GREEN  = YES
PRODUCTION_MUTATION                 = 0
```

Promotion is never implied by this document alone; each promotion is a separate
issue with its own CTO work contract.

---

## 7. Existing Regression Guard

`apps/padiem-chat/tests/test_claw_chat_preview.py::test_claw_static_assets_preserve_disabled_controls_and_safe_dom_sinks`
already asserts the disabled state of all five Group A controls, including the exact
string `claw-disabled-control" disabled aria-disabled="true"` and each Korean label.
Any future promotion must update that test in the same change as the UI change.

---

## 8. Watch Items (recorded, not defects, out of #2089 scope)

1. **Copy drift risk** — the Group A download notes say "백엔드 연결 전까지 비활성화",
   while `md`/`docx` generation already exists. See the capability-versus-endpoint
   distinction in section 4.
2. **Skills dialog badges** — five skill cards in `#skillsDialog` carry no "준비 중"
   badge while "사용자 정의 스킬 만들기" does. Currently unreachable because
   `#skillsNavButton` is disabled, but should be badged before that nav is enabled.
   Not a Claw connector/action; recorded for awareness only.

---

## 9. Non-Action Attestations for This Document

```text
CONNECTOR_GRANT_MUTATION = NO
PROVIDER_CALLS           = 0
CREDENTIAL_WORK          = 0
DB_STORAGE_MUTATION      = 0
EMAIL_SEND               = 0
GOOGLE_DRIVE_LIVE_CALL   = 0
GMAIL_LIVE_CALL          = 0
UI_SOURCE_CHANGE         = NO
LOCALE_CHANGE            = NO
TEST_CHANGE              = NO
DEPLOY                   = NO
PRODUCTION_MUTATION      = 0
```

---

## 10. References

- #2089 — parent audit issue
- #2056 — Claw manual message intake architecture and safety boundary
- #2016 — Claw document export (`md`/`docx`/`hwpx` decisions)
- #2058 — Claw automation boundary
- #2055 — backing storage referenced by `share_link_requires_storage_2055`
- #1908 — Control Plane Google OAuth boundary
- #2075, #2084, #2086, #2057, #2010 — related Claw/connector workstreams
