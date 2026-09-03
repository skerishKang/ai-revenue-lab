# B54 SMS Connector Safety v1

Status: repository-side preparation  
Parent: #1647  
Implementation: #1694  
Korea/provider verification date: 2026-09-03

## Boundary

Padiem Claw exposes provider-neutral semantic capabilities:

```text
sms.send_text
sms.send_template
sms.delivery_status
```

MMS/media, bulk campaigns, arbitrary sender substitution, contact scraping and phone-number enumeration are outside v1.

No Production SMS provider is selected by this repository slice. Provider selection remains an external commercial/live gate based on Korea/global coverage, registered-sender support, price, delivery receipts, API reliability, quotas and operational requirements.

## Identity and PII

`SmsBinding` binds:

```text
trusted connector binding
Padiem workspace
provider account
provider-registered sender profile
explicit opaque recipient refs
```

A phone number is trusted PII held in the adapter/contact-mapping authority. It is not a B54/model-safe recipient identifier. Phone-shaped values are rejected as `recipient_ref`, and safe projections expose counts rather than recipient lists.

The model cannot invent, enumerate, scrape or sequentially generate recipients.

## Sender identity

A sender must be represented by `SmsSenderProfile` with trusted provider-registration evidence. The model supplies only the approved `sender_ref`; it cannot replace the underlying telephone/caller number.

This is consistent with the current Korean caller-number protection boundary: provider adapters must not enable false/manipulated caller-number display.

## Purpose classification

SMS purpose is explicit:

```text
TRANSACTIONAL
ADVERTISING
```

Authentication codes, order/payment/delivery and required service notices can be modeled as transactional only when the actual content is non-promotional.

If transactional content includes promotional/commercial inducement, Padiem fails closed and requires advertising treatment. The model cannot downgrade a mixed message to avoid consent/compliance gates.

## Advertising consent and quiet hours

Current Korean Information and Communications Network Act Article 50 requires explicit prior consent for commercial advertising information unless a statutory exception applies. Padiem does not infer legal exceptions from model output.

Advertising preflight requires:

```text
active recipient advertising consent evidence
sender identity present
(광고) / provider-required advertising indication
free/easy opt-out path
```

For advertising scheduled during:

```text
21:00 KST <= night period < 08:00 KST
```

`SmsAdvertisingConsent` must also contain separate trusted night-advertising consent evidence. General advertising consent is insufficient for the night window.

Opt-out or consent withdrawal must be honored by trusted recipient eligibility state before execution. If a selected provider offers an 080 free-unsubscribe service, its binding and synchronization become part of the live provider gate.

## No automatic contact generation

Repository policy explicitly rejects:

```text
phone-number guessing
sequential enumeration
address-book scraping
automatic advertising recipient registration
hiding sender/source identity
bypassing opt-out state
```

These are not merely prompting preferences; they are outside the connector authority model.

## Rate budget

`SmsRateBudget` gives deterministic fail-closed bounds for:

```text
per-run sends
workspace hourly sends
per-recipient cooldown
```

Repository defaults are conservative safety ceilings, not provider quotas:

```text
max per run = 100
max per workspace/hour = 1000
minimum recipient cooldown = 30 seconds
```

A live product policy may set lower values. Higher or campaign-scale limits require a separately reviewed bulk/campaign capability rather than silently weakening this contract.

Initial v1 execution is exactly one recipient per approved `ConnectorWriteIntent`.

## Approval material

`SmsOutboundMaterial` fingerprints exact:

```text
binding/workspace
provider
sender
opaque recipient
transactional/advertising purpose
text SHA-256
schedule
template identity + revision when used
workflow
```

Any sender, recipient, content, purpose, schedule or template change changes the material fingerprint and invalidates prior P01 approval.

The shared write intent must match:

```text
connector_id = sms
tool_name = sms.send_text OR sms.send_template
binding_ref = exact binding
target_ref = exact sender + opaque recipient target
payload_fingerprint = exact material fingerprint
expected_version_ref = sms-material:<fingerprint>
approval_ref = exact P01 approval
evidence_ref = exact P01 evidence
idempotency_key = exact trusted retry key
```

Duplicate retries must pass through the shared connector idempotency/dedup execution boundary. A retry is not authority to create another semantically new SMS.

## Delivery evidence

Provider request acceptance and handset delivery are distinct states:

```text
ACCEPTED
DELIVERED
FAILED
UNKNOWN
```

`SmsOutboundReceipt` correlates the shared write receipt to the exact provider message/request ref. Failed delivery requires bounded failure-reason evidence. Generated model text or an HTTP 2xx alone is not final delivery evidence unless the selected provider contract explicitly defines that result as final delivery.

Safe receipts never include a full recipient phone number or provider credential.

## Provider selection gate

The first live provider must be separately evaluated for:

1. Korean sender-number registration and identity verification;
2. SMS/LMS support and encoding/length behavior;
3. opt-out/080 support for advertising workflows;
4. delivery/status callback or polling quality;
5. idempotency/dedup options;
6. rate/quota behavior;
7. Korea/global coverage;
8. price and commercial terms;
9. credential rotation/revocation;
10. sandbox/non-Production canary support.

Candidate evaluation does not equal Production selection.

## Explicit non-authority

```text
PROVIDER_NEUTRAL_PORT = YES
PRODUCTION_PROVIDER_SELECTED = NO
TRUSTED_REGISTERED_SENDER = REQUIRED
ARBITRARY_MODEL_SENDER = NO
PHONE_NUMBER_IN_MODEL_SAFE_STATE = NO
PHONE_NUMBER_GENERATION_ENUMERATION = NO
MIXED_CONTENT_DEFAULTS_ADVERTISING = YES
NIGHT_ADVERTISING_CONSENT_21_08_KST = REQUIRED
ONE_RECIPIENT_PER_APPROVED_WRITE = YES
AUTONOMOUS_BULK_SMS = NO
MMS_V1 = NO
RAW_PROVIDER_SECRET_IN_B54 = NO
REAL_SMS_PROVIDER_CONFIGURED = NO
REAL_SMS_SEND_CONFIGURED = NO
PRODUCTION_MUTATION = NO
```

## Live gate still required

#1647/#1569 remain responsible for:

1. fresh provider comparison and explicit first-provider choice;
2. account/commercial onboarding and trusted credentials;
3. provider-registered sender-number verification/readback;
4. trusted recipient-ref ↔ phone-number mapping and privacy review;
5. advertising consent/withdrawal/080 synchronization where advertising is selected;
6. separate night-advertising consent evidence path;
7. non-Production single-recipient transactional canary;
8. separately approved advertising canary only after consent/compliance proof;
9. duplicate/idempotency negative canary;
10. rate-limit/cooldown canary;
11. delivery/failure/unknown receipt reconciliation;
12. credential revocation, sender disablement and rollback/incident-response proof.

Repository-side completion is not provider selection, legal certification, real-send authority or Production approval.
