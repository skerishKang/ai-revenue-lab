# B54 Kakao Business Messaging Safety v1

Status: repository-side preparation  
Parent: #1646  
Implementation: #1690  
Kakao verification date: 2026-09-03

## Provider truth

Padiem Claw uses official Kakao Business messaging products only. Personal KakaoTalk session/cookie scraping, address-book scraping, or unofficial automation is outside this connector boundary.

Current Kakao product roles are kept separate:

```text
ALIMTALK
  service/channel -> user
  informational messages only
  Kakao-reviewed/approved template required

BRAND_MESSAGE
  service/channel -> user
  advertising/marketing
  recipient eligibility depends on current Kakao product rules
  official dealer/API gate

CHANNEL_MESSAGE
  KakaoTalk Channel -> channel friend
  advertising/marketing channel message

CS_TALK
  customer-support conversation
  user initiates consultation first
```

Kakao Developers also provides Kakao Talk Message API for a logged-in user sending messages to selected Kakao friends. That user-to-friend feature is not treated as the Padiem business-notification connector.

## Dealer and credential boundary

AlimTalk and Brand Message are provided through Kakao official dealers. The exact live dealer/API contract can differ in endpoint names, receipt format, quotas, and asynchronous delivery states.

Therefore repository contracts bind only stable Padiem semantics:

```text
workspace
business account
KakaoTalk Channel
official dealer binding
enabled Kakao product
explicit recipient
```

Raw app keys, dealer API keys, access tokens, cookies, phone-number lists, and personal Kakao credentials never enter model/task state.

## Recipient scope

`KakaoBusinessBinding` contains an explicit recipient allowlist. The model cannot discover or scrape arbitrary Kakao users.

Safe projection exposes only recipient count, never the recipient list.

Initial write contract is one recipient per approved write:

```text
recipient_count = 1
bulk_send = false
```

Bulk or campaign sending requires a separate reviewed capability, recipient-set evidence, compliance policy and explicit authorization.

## AlimTalk

AlimTalk is modeled as informational only.

Required preflight state:

```text
purpose = informational
template review state = approved
template_ref = exact reviewed template
template_revision_ref = exact reviewed revision
variable keys = exact approved set
rendered text/material fingerprint = exact approved P01 material
promotional content = false
```

A pending/rejected/suspended template cannot be used.

Changing the template revision, variable-key set, rendered text, links, buttons or attachments changes the Padiem material fingerprint and invalidates the prior approval.

Kakao's current AlimTalk guidance permits only information that falls within the recognized informational-message exceptions and has passed Kakao template review. Mixed informational + promotional content does not silently remain AlimTalk authority.

## Advertising eligibility

Advertising surfaces distinguish recipient eligibility from generic OAuth/account access.

`KakaoAdvertisingEligibility` supports:

```text
CHANNEL_FRIEND
MARKETING_CONSENT
```

For Channel Message, the initial Padiem contract requires exact current channel-friend evidence.

For Brand Message, the contract may accept a current channel-friend or separately evidenced KakaoTalk marketing-consent eligibility where the selected live Kakao product/dealer contract permits it.

Inactive, future-dated, mismatched-recipient or missing eligibility fails closed.

## Advertising compliance

Current Kakao channel/message-ad guidance requires advertising messages to preserve:

```text
(광고) indication
sender name
sender contact
easy opt-out / consent-withdrawal method
```

Information mixed with promotion is treated as advertising unless a documented exception applies.

The repository contract also enforces the currently documented Kakao advertising quiet-hours boundary:

```text
21:00 KST <= quiet period < 08:00 KST
```

Generic Padiem preflight allows advertising scheduling from 08:00 through before 21:00 KST. A selected Kakao product/dealer may impose a narrower operational window; the live adapter must honor the narrower provider rule.

No model decision can waive provider policy or Korean advertising-message compliance.

## CS Talk

CS Talk is not an unsolicited outbound channel.

`KakaoCsSession` requires:

```text
exact recipient
exact session
user_initiated = true
active session
trusted session evidence
```

Padiem cannot turn a closed/non-user-initiated CS session into marketing authority.

Inbound customer text remains untrusted data and requires the existing connector inbound/tool authority boundary before any action is taken.

## Material approval

`KakaoOutboundMaterial` binds:

```text
binding/workspace
product
purpose
recipient
text SHA-256
template identity/revision
variable keys + variable payload fingerprint
buttons/links/attachment fingerprints
CS session identity
workflow
```

The resulting `material_fingerprint` is bound to:

```text
P01 approval_ref
P01 evidence_ref
ConnectorWriteIntent.payload_fingerprint
ConnectorWriteIntent.expected_version_ref
idempotency_key
```

Any material change requires new approval.

Semantic tool names are product-specific:

```text
kakao.alimtalk.send
kakao.brand_message.send
kakao.channel_message.send
kakao.cs_talk.send
```

Provider/dealer endpoint names are adapter concerns and must not redefine P01 semantics.

## Delivery evidence

A successful API request is not automatically final delivery.

`KakaoDeliveryEvidence` distinguishes:

```text
accepted
delivered
failed
unknown
```

It binds the exact provider/dealer request reference and status evidence. A failed result requires a bounded failure-reason reference.

`KakaoOutboundReceipt` requires the shared `ConnectorWriteReceipt.provider_operation_ref` to match the exact Kakao/dealer request reference before delivery evidence is accepted.

Generated model text is never delivery evidence.

## Explicit non-authority

```text
OFFICIAL_KAKAO_BUSINESS_ONLY = YES
PERSONAL_KAKAOTALK_SESSION_AUTOMATION = NO
ADDRESS_BOOK_SCRAPING = NO
ALIMTALK_APPROVED_TEMPLATE_REQUIRED = YES
MIXED_CONTENT_DEFAULTS_ADVERTISING = YES
ADVERTISING_ELIGIBILITY_EVIDENCE = REQUIRED
CHANNEL_MESSAGE_CHANNEL_FRIEND_EVIDENCE = REQUIRED
ADVERTISING_QUIET_HOURS_KST = 21:00-08:00
ONE_RECIPIENT_PER_APPROVED_WRITE = YES
RAW_KAKAO_CREDENTIAL_IN_B54 = NO
REAL_KAKAO_BUSINESS_CONFIGURED = NO
REAL_KAKAO_SEND_CONFIGURED = NO
PRODUCTION_MUTATION = NO
```

## Live gate still required

#1646/#1569 remain responsible for:

1. selecting the exact Kakao Business product(s) needed by Padiem;
2. official Kakao Business/Channel verification;
3. official dealer selection and commercial/API contract;
4. trusted dealer/API credentials and channel/account binding;
5. live sender/channel identity readback;
6. AlimTalk template registration/review and exact approved-template readback;
7. recipient/phone mapping authority and privacy review;
8. channel-friend / marketing-consent eligibility evidence according to the selected product;
9. advertising compliance and provider-specific scheduling-window verification;
10. one-recipient non-Production AlimTalk canary;
11. separately approved advertising canary only after consent/compliance proof;
12. user-initiated CS Talk canary if CS Talk is selected;
13. delivery/failure receipt ingestion and exact request correlation;
14. rate/quota/fallback behavior;
15. credential revocation, rollback and incident-response verification.

Repository-side completion does not imply Kakao account approval, dealer readiness, live send authority, legal certification, or Production approval.
