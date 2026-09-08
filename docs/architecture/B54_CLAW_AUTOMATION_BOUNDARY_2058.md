# B54 Claw Automation, Scheduled Checks, and Notification Delivery Channels (#2058)

- Status: REVIEWED / ACT-0 & ACT-1
- Target Milestone: Claw Automation MVP
- Scope: Workspace-scoped scheduled checks, rule models, notification proposals, delivery channel boundaries, and approval gates
- Production Scheduler / Live Connector Calls: NONE (Contract & Deterministic In-Memory Simulation Only)

---

## 1. Executive Summary & Core Safety Invariants

Padiem Claw (B54) automation enables periodic and trigger-based checks for autonomous agent operations (e.g. tracking overdue quotes, pending purchase orders, invoice collection, or sync checks).

To maintain strict safety and user control:
- **Workspace-Scoped**: Every rule, schedule, run, and alert is bound to an explicit `workspace_id`.
- **Output Limited**: Automation outputs are strictly confined to:
  1. `alert` (user-visible notification in Web Alert Inbox)
  2. `draft` (un-sent document draft, e.g. follow-up email draft)
  3. `report` (read-only audit or reconciliation summary)
  4. `task_proposal` (bounded agent task proposal requiring admission)
- **Zero Automatic Side-Effects**:
  - `AUTO_SEND = NO`: No outbound emails, Kakao messages, SMS, or Slack alerts sent automatically.
  - `AUTO_ORDER = NO`: No purchase orders or deal acceptances created automatically.
  - `AUTO_MEMORY_CONFIRM = NO`: No workspace memory facts permanently confirmed without user review.
- **Approval Gate Required**: Any irreversible or external side-effect generates an `approval_required` proposal.

### Non-Negotiable Boundary Table
```text
WORKSPACE_SCOPED_SCHEDULED_CHECKS = YES
WEB_ALERT_INBOX_DELIVERY = YES
EMAIL_NOTIFICATION_OPTION = DEFERRED_OR_GATED
TELEGRAM_DISCORD_NOTIFICATION = LATER
KAKAO_SMS_NOTIFICATION = LATER_POLICY_GATED
AUTO_SEND = NO
AUTO_ORDER = NO
AUTO_MEMORY_CONFIRM = NO
CONNECTOR_RUNTIME_REIMPLEMENTED = NO
REAL_CRON_REGISTRATION = NO
PROVIDER_CALLS = 0
CREDENTIAL_WORK = 0
PRODUCTION_MUTATION = 0
```

---

## 2. Schedule Representations & Dayparts

Claw automation supports multiple schedule expressions:
1. `CRON`: Standard 5-field cron syntax (`minute hour day-of-month month day-of-week`).
2. `INTERVAL`: Bounded repetition interval (e.g. every `N` minutes/hours/days).
3. `DAYPART`: Human-centric business dayparts:
   - `morning` (09:00 KST / 00:00 UTC)
   - `midday` (12:00 KST / 03:00 UTC)
   - `evening` (18:00 KST / 09:00 UTC)
   - `close_of_business` (20:00 KST / 11:00 UTC)

All schedules evaluate against deterministic timestamps and timezone-aware datetimes.

---

## 3. Notification Delivery Channels & Tiered Availability

Claw organizes notification delivery into progressive tiers:
1. **Tier 1 — Web Alert Inbox (Current MVP)**:
   - Local, user-visible inbox inside Padiem web/chat console.
   - Always available; default delivery for all generated alerts.
2. **Tier 2 — Email (Deferred / Approval Gated)**:
   - Formats draft notification; requires explicit approval or verified outbox clearance before dispatch.
3. **Tier 3 — Telegram & Discord (Later)**:
   - Read-only alert delivery to configured bot webhook channels (future milestone).
4. **Tier 4 — Kakao Business & SMS (Later Policy Gated)**:
   - Alimtalk / SMS templates governed by strict carrier template review and recipient opt-in verification. Direct automated personal Kakao messaging is forbidden.

---

## 4. Bounded Projections & Security Redaction

Safe run projections and alert outputs must never leak:
- Raw connector tokens or API secrets.
- Raw cloud provider errors.
- Internal agent reasoning loops.
- File system paths outside workspace boundary.
