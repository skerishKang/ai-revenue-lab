# Padiem Kakao OTP Signup Contract v1

Status: repository-side simulation / reusable auth contract  
Issue: #1697  
Authority: `packages/padiem-control-plane`  
Transport simulator: `apps/korean-ai-code-agent/src/kagent/kakao_otp_simulator.py`

## Product decision

Initial signup UI is channel-neutral:

```text
Email
Phone number
[Send verification code]
Verification code
[Verify]
[Sign up]
```

There is no SMS-specific UI. The server chooses the approved transport. Initial development transport is a network-free Kakao simulator. SMS remains a backend/future fallback capability only.

## Authority split

```text
Product edge (Padiem Claw / DanjiOn / future product)
  - collect raw email and phone
  - normalize and store PII in trusted product/identity storage
  - resolve opaque email_contact_ref / phone_contact_ref / network_ref
        |
        v
Padiem Control Plane
  - OTP challenge lifecycle
  - HMAC digest only at rest
  - expiry / attempts / lockout
  - resend cooldown and rate-budget contract
  - one-time verification receipt
        |
        v
Transport adapter
  - Kakao simulator now
  - real Kakao AlimTalk later
  - optional SMS fallback later
```

B54 does not become an identity database and the model never becomes the authority for contact verification.

## Core lifecycle

1. Product receives email + phone in a trusted signup endpoint.
2. Product resolves opaque refs:
   - `email_contact_ref`
   - `phone_contact_ref`
   - `network_ref`
   - `signup_session_ref`
3. Trusted server calls `issue_otp_challenge(...)`.
4. Control Plane generates a cryptographically strong six-digit OTP.
5. Persist only `OtpVerificationChallenge`; it contains an HMAC-SHA256 digest, never the raw OTP.
6. Pass the ephemeral `OtpIssueResult.delivery_code` directly to the trusted Kakao transport, then discard it from application state.
7. User enters the code in the same signup form.
8. Trusted server calls `verify_otp_challenge(...)`.
9. On success, consume `ContactVerificationReceipt` and mark that phone contact verified for that exact signup session.
10. The verified challenge cannot be consumed twice.

## OTP hashing

The digest is bound to:

```text
challenge_id
product_id
signup_session_ref
email_contact_ref
phone_contact_ref
OTP code
server-held pepper
```

The pepper is supplied by secret authority at runtime and is not stored in the challenge. This is stronger than storing a plain SHA-256 of a six-digit code.

## Default safety parameters

```text
OTP digits                = 6
OTP lifetime              = 300 seconds
max challenge lifetime    = 600 seconds
resend cooldown           = 60 seconds
max attempts              = 5
rate window               = 1 hour
max issues / signup       = 5
max issues / phone ref    = 5
max issues / network ref  = 20
```

These are repository defaults, not a legal/provider requirement. Product deployments may narrow them.

## Rate limiting

`VerificationRateSnapshot` is a product-neutral trusted projection. Persistent counters remain an implementation responsibility of the server/store.

The contract requires independent budget dimensions for:

```text
signup session
phone contact ref
network ref
```

Raw IP addresses and raw phone numbers do not enter the model-safe contract.

## Resend

A resend does not revive the old code.

```text
old challenge -> SUPERSEDED
new challenge -> generation + 1
```

The old challenge cannot verify even if the old code is known.

## Wrong attempts / lockout

Each failed code consumes one attempt. At the configured maximum the challenge becomes `LOCKED`. A locked challenge cannot be recovered in place; a fresh challenge requires the resend/rate gates.

## Expiry

At or after `expires_at`, verification returns `EXPIRED`. Expired codes cannot become valid again.

## Verification receipt

Successful verification returns a `ContactVerificationReceipt` bound to the exact:

```text
receipt_id
challenge_id
product_id
signup_session_ref
email_contact_ref
phone_contact_ref
channel
verified_at
```

Public projection explicitly records:

```text
phone_verified = true
identity_assurance = contact_possession_only
legal_identity_verified = false
```

This distinction must be preserved by every consumer, including DanjiOn.

## Fake Kakao simulator

`FakeKakaoOtpInbox(test_mode=True)` simulates what the user would receive in KakaoTalk without network access or provider cost.

The raw OTP exists only inside the in-memory test fixture. Normal safe projections expose:

```text
delivery_ref
challenge_id
phone_contact_ref
template_ref
delivered_at
expires_at
transport = kakao_simulated
raw_phone_present = false
raw_otp_present = false
real_provider_send = false
```

There is no Production endpoint that returns the test OTP. Automated tests may use `read_code_for_test()` only on the explicit test fixture.

## Production transport swap

Development:

```text
Control Plane OTP Core
  -> FakeKakaoOtpInbox
```

Future Production:

```text
Control Plane OTP Core
  -> RealKakaoAlimTalkAdapter
  -> approved Kakao business template / official dealer
```

The signup UI and verification core do not change when the transport changes.

Real AlimTalk requires separate business/dealer/template/provider approval and may incur cost. Repository simulation does not claim that live Kakao messaging is free or configured.

## Kakao Login optimization

A future product may use Kakao Login/Kakao Sync and trusted verified phone data where available. If the trusted identity adapter can establish the required verified contact state, product policy may skip a separate OTP challenge. That is a separate identity adapter path and must not be inferred by the model.

## SMS fallback

SMS remains backend-only in the initial product:

```text
SMS-specific UI = NO
SMS provider selection = separate gate
SMS real send = NO in repository simulation
```

If Kakao delivery is unavailable later, server policy may select an approved SMS fallback without changing the signup form.

## HTTP integration shape

Recommended product API:

```text
POST /auth/verification/start
POST /auth/verification/verify
POST /auth/signup
```

### Start

Input at trusted product edge:

```json
{
  "email": "user supplied email",
  "phone": "user supplied phone"
}
```

Response:

```json
{
  "challenge_id": "opaque challenge ref",
  "delivery_channel": "kakao",
  "expires_in_seconds": 300,
  "resend_after_seconds": 60
}
```

Never return the OTP.

### Verify

Input:

```json
{
  "challenge_id": "opaque challenge ref",
  "code": "six digits"
}
```

Success response may return a short-lived opaque verification receipt/token reference. Do not return raw contact PII if the client already has it.

### Sign up

`/auth/signup` must require a valid verification receipt bound to the same signup session/contact refs. A client-side `phone_verified=true` flag is never authority.

## Repository status

```text
CHANNEL_NEUTRAL_SIGNUP_UI = YES
SMS_UI = NO
PRIMARY_SIMULATED_TRANSPORT = KAKAO
OTP_SERVER_GENERATED = YES
OTP_HMAC_DIGEST_ONLY_AT_REST = YES
OTP_ONE_TIME = YES
OTP_EXPIRY = YES
OTP_RESEND_COOLDOWN = YES
OTP_ATTEMPT_LOCKOUT = YES
OTP_RATE_BUDGET = YES
RAW_PHONE_IN_MODEL_SAFE_STATE = NO
REAL_KAKAO_SEND = NO
REAL_PROVIDER_COST = NO
LEGAL_IDENTITY_VERIFICATION = NO
PRODUCTION_MUTATION = NO
```
