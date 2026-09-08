# B54 Claw Manual Message Intake Architecture & Safety Boundary (#2056)

- Status: REVIEWED / ACT-0 & ACT-1
- Issue: #2056 — [B54/B62][Claw MVP] Manual message intake in Padiem Chat shell — paste request to quote/order document
- Scope: Connectorless manual text intake for quote, order, reply, summary, and candidate extraction
- Collision Boundary: `apps/padiem-chat/static/**` is strictly untouched (reserved for FREEBUFF #2062)

---

## 1. Executive Summary

Claw manual message intake allows a business user to paste unstructured inbound messages (from KakaoTalk, SMS, Email, Telegram, Discord, or other business messengers) directly into Claw to generate actionable business artifacts without requiring active connector integrations.

### Safety Invariants
```text
CONNECTOR_REQUIRED_FOR_MANUAL_INTAKE = NO
RAW_INPUT_TRUSTED_AS_MEMORY = NO (untrusted ephemeral input only)
MEMORY_UPDATE_REQUIRES_USER_APPROVAL = YES (proposals only)
DOCX_DOWNLOAD = YES_WHERE_2016_AVAILABLE
HWPX_DOWNLOAD = DOCUMENTED_DECISION (fails closed per #2016)
EMAIL_SEND_REQUIRES_USER_APPROVAL = YES (no auto-send)
DIRECT_KAKAO_SEND = NO (forbidden)
DIRECT_SMS_SEND = NO (forbidden)
SHARE_LINK_REQUIRES_2055 = YES (disabled without backing storage)
GOOGLE_DRIVE_SAVE_REQUIRES_CONNECTOR = YES (disabled without connector)
PROVIDER_CALLS = 0
CREDENTIAL_WORK = 0
PRODUCTION_MUTATION = 0
```

---

## 2. Channel & Action Support

### Channels (`ManualIntakeChannel`):
- `kakao` (KakaoTalk message paste)
- `sms` (SMS/MMS text paste)
- `email` (Email message body paste)
- `telegram` (Telegram chat paste)
- `discord` (Discord message paste)
- `other` (Generic / clipboard text)

### Actions (`ManualIntakeAction`):
1. `quote_draft`: Generates 견적서 초안 (DRAFT) and 산출 근거 table.
2. `order_draft`: Generates 발주서/판매오더 초안 (DRAFT) from quote context.
3. `reply_draft`: Prepares a professional Korean polite business reply draft.
4. `summarize_request`: Extracts key intent, customer name, requested items, delivery constraints.
5. `extract_candidates`: Extracts candidate customer/contact/item facts as unconfirmed memory proposals.

---

## 3. Untrusted Memory Boundary

- Pasted text is strictly **untrusted input**.
- It must **NEVER** directly modify or be automatically committed to workspace memory.
- Any extracted business context (e.g. company name, VAT registration number, contact person) is exported strictly as a `memory_proposal` requiring explicit user review and approval before permanence.

---

## 4. Downloadable Artifacts & Disabled Actions Contract

### Artifacts:
- Locally generated text is downloadable as `.md`.
- Where #2016 DOCX export is available, a valid `.docx` OOXML artifact is generated and downloadable.
- `.hwpx` follows the #2016 documented decision and fails closed with a clear error.

### Disabled / Gated Actions:
- `direct_kakao_send`: Disabled (policy forbids direct automated personal Kakao sending).
- `direct_sms_send`: Disabled.
- `email_send`: Approval-gated (disabled unless approved and outbound provider configured).
- `share_link`: Disabled unless backed by #2055 `WorkspaceShareLink`.
- `google_drive_save`: Disabled unless authorized Google Drive connector is attached.
