# B54 Gmail Bounded Context + Draft/Send Approval v1

Status: repository-side preparation  
Parent: #1639  
Implementation: #1664  
Google verification date: 2026-09-03

## Provider truth

Current Google Workspace MCP documentation exposes these Gmail tools:

```text
create_draft
get_message
get_thread
label_message
label_thread
list_drafts
list_labels
search_threads
unlabel_message
unlabel_thread
```

There is no Gmail MCP send tool in the current published list. Google's own MCP
example creates a draft and tells the user to review/send it in Gmail.

Current Google configuration guidance requests:

```text
gmail.readonly
gmail.compose
```

Important: `gmail.compose` is not a draft-only OAuth permission. Google's OAuth scope
description says it manages drafts and sends mail, and Gmail REST `users.drafts.send`
also accepts `gmail.compose`.

Therefore Padiem must not treat provider OAuth scope as product send authority:

```text
provider credential can technically send
          !=
Padiem Agent may send
```

P01 remains the authority that permits `SEND_EXISTING_APPROVED_DRAFT`.

Official references reviewed:

- `https://developers.google.com/workspace/guides/configure-mcp-servers`
- `https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server`
- `https://developers.google.com/identity/protocols/oauth2/scopes`
- `https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create`
- `https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/send`

## Capability boundary

B54 defines four explicit capabilities:

```text
READ
CREATE_DRAFT
SEND_EXISTING_APPROVED_DRAFT
LABEL_MUTATION
```

`CREATE_DRAFT` never implies `SEND_EXISTING_APPROVED_DRAFT` even when both physical
operations could be executed using the same Google OAuth scope.

Current MCP transport can be used for reads and draft creation after trusted OAuth
wiring. Send remains a separately reviewed physical Gmail API adapter/canary.

## Mail is untrusted input

`GmailMessageProjection` keeps bounded headers and message identity separate from
body content.

Projected fields include:

- message id;
- thread id;
- From;
- To / Cc / Bcc;
- subject;
- date header;
- label ids;
- history/internal-date refs;
- bounded body segments;
- attachment manifests.

All body segments — plain body, converted HTML text, quoted chains, forwarded text
and signatures — remain `trusted_instruction = false`.

No email body can create Tool, Skill, Approval or connector authority.

## Thread bounds

Repository defaults:

```text
MAX_THREAD_MESSAGES = 8
MAX_MESSAGE_BODY_CHARS = 20,000
MAX_THREAD_BODY_CHARS = 60,000
```

This is a Padiem context-safety limit, not a Gmail provider limit.

The product does not support dumping an entire mailbox into model context.

## Attachments

Gmail message parts expose attachment id, filename, MIME type and byte size. Actual
attachment data is fetched separately from `users.messages.attachments.get`.

B54 therefore projects a `GmailAttachmentManifest` first and keeps:

```text
raw_bytes_present = false
```

An attachment is model-usable only after quarantine has produced all three trusted
facts:

```text
quarantine_state = accepted
sha256 = exact content digest
quarantine_evidence_ref = trusted evidence reference
```

An `accepted` attachment without both the SHA-256 digest and trusted quarantine
evidence ref fails closed. Pending/rejected attachments are not allowed to carry an
accepted-quarantine evidence ref.

Repository default quarantine ingress is capped at 10 MiB per attachment for this
workflow; this is intentionally narrower than provider mail-size limits.

No attachment is executed automatically, and raw attachment bytes never enter model
context merely because Gmail returned an attachment id.

## Draft material snapshot

Before send approval, a trusted draft read produces `GmailDraftMaterialSnapshot`.
It binds:

- exact connector binding/workspace;
- exact draft id and current message id;
- sender/from alias;
- To, Cc and Bcc recipients;
- subject;
- body SHA-256;
- exact approved attachment ref;
- attachment filename;
- attachment MIME type;
- attachment byte size;
- attachment SHA-256;
- trusted quarantine evidence ref;
- thread id;
- reply message ref.

Only `GmailApprovedAttachment` values that already carry these accepted-quarantine
facts may enter the send material snapshot.

The canonical snapshot produces a deterministic SHA-256 `material_fingerprint`.
Recipient order within To/Cc/Bcc is normalized for the fingerprint, but moving an
address between those header classes remains a material change. Any attachment MIME,
size, hash or quarantine-evidence change is also a material change and invalidates the
previous approval.

Repository safety cap:

```text
MAX_APPROVED_RECIPIENTS = 20
```

No autonomous mass-send capability is defined.

## Send approval

`GmailSendApprovalBinding` records the P01 approval/evidence refs and the exact
material fingerprint approved.

A send `ConnectorWriteIntent` must bind:

```text
connector_id = gmail
tool_name = send_existing_approved_draft
target_ref = exact draft id
payload_fingerprint = exact material fingerprint
expected_version_ref = gmail-draft:<material fingerprint>
approval_ref = exact P01 approval
evidence_ref = exact P01 evidence
idempotency_key = exact write key
```

`gmail_send_preflight()` refuses if:

- connector/tool is not the exact send capability;
- binding or draft id changed;
- approval/evidence changed;
- any recipient, subject, body hash, attachment, sender or reply/thread material
  changed;
- write intent fingerprint changed;
- expected material-version binding changed.

Draft creation itself can never satisfy this preflight.

## Delivery evidence

Google REST `users.drafts.send` sends an existing draft and returns a Gmail Message.
When a live adapter is later enabled, `GmailSendReceipt` must wrap the shared trusted
`ConnectorWriteReceipt` and include returned sent message/thread ids.

```text
provider delivery receipt = evidence
model generated text       != delivery evidence
```

## Remaining external gates

#1639 remains open until:

1. trusted Gmail OAuth/account binding is live;
2. read-only mailbox/thread canary passes within bounded scope;
3. real attachment quarantine pipeline is wired and emits trusted evidence refs;
4. MCP `create_draft` live canary passes with P01 policy/evidence;
5. separately reviewed Gmail API `drafts.send` adapter is wired;
6. exact draft readback -> P01 approval -> send preflight -> provider receipt canary
   passes;
7. rollback/recovery and operational disable path are verified.

```text
GMAIL_MCP_CREATE_DRAFT_SUPPORTED = YES
GMAIL_MCP_SEND_TOOL_SUPPORTED = NO
GMAIL_PROVIDER_COMPOSE_SCOPE_INCLUDES_SEND = YES
GMAIL_PROVIDER_SCOPE_ALONE_GRANTS_PADIEM_SEND_AUTHORITY = NO
GMAIL_SEND_REQUIRES_P01_APPROVAL = YES
GMAIL_ATTACHMENT_QUARANTINE_REQUIRED = YES
GMAIL_ACCEPTED_ATTACHMENT_REQUIRES_TRUSTED_EVIDENCE = YES
GMAIL_BULK_MAILBOX_DUMP_SUPPORTED = NO
GMAIL_AUTONOMOUS_MASS_SEND_SUPPORTED = NO
REAL_GMAIL_SEND_CONFIGURED = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
