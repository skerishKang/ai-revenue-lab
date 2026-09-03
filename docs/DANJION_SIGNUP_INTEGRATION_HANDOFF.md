# DanjiOn Signup Integration Handoff — Padiem Kakao OTP v1

Status: implementation handoff contract  
Canonical auth core: `packages/padiem-control-plane/padiem_control_plane/contact_verification.py`  
Development Kakao transport: `apps/korean-ai-code-agent/src/kagent/kakao_otp_simulator.py`

## Objective

Implement DanjiOn signup without creating a DanjiOn-specific OTP algorithm.

DanjiOn owns its signup UI, account persistence and apartment-domain rules. Padiem Control Plane owns the reusable contact-verification challenge contract.

## DanjiOn signup UI

Required initial fields:

```text
Email
Phone number
[인증번호 받기]
Verification code
[인증 확인]
[가입하기]
```

Do not add:

```text
SMS/Kakao transport selector
SMS-specific signup screen
raw OTP debug field
```

The transport is server policy. Development default is Kakao simulator.

## Required DanjiOn backend boundary

Implement three product endpoints or equivalent application commands:

```text
POST /auth/verification/start
POST /auth/verification/verify
POST /auth/signup
```

### `/auth/verification/start`

Responsibilities:

1. validate/normalize email and phone at the trusted server edge;
2. never pass raw email/phone into model/tool context;
3. create or resolve opaque refs:
   - `email_contact_ref`
   - `phone_contact_ref`
   - `network_ref`
   - `signup_session_ref`;
4. load persistent rate counters;
5. call Padiem `issue_otp_challenge(...)`;
6. persist the challenge + updated rate counters;
7. pass the ephemeral delivery code to the configured Kakao transport;
8. immediately discard the raw code from application state;
9. return only challenge timing/channel metadata to the browser.

### `/auth/verification/verify`

Responsibilities:

1. look up the exact challenge by opaque challenge id;
2. submit the user-entered code to `verify_otp_challenge(...)`;
3. persist attempt/state changes even on a failed code;
4. on success persist/consume `ContactVerificationReceipt`;
5. mark the phone contact verified only for the bound signup session/account creation flow;
6. never trust browser-provided `phone_verified` state.

### `/auth/signup`

Require:

```text
same signup session
same email_contact_ref
same phone_contact_ref
valid unused verification receipt
```

Consume or bind the receipt during account creation so it cannot authorize another account creation.

## Suggested DanjiOn persistence fields

Exact DB schema is product-owned, but preserve these semantics.

### Contact table / account contact fields

```text
email_normalized (trusted PII storage)
phone_normalized (trusted PII storage)
email_contact_ref (opaque)
phone_contact_ref (opaque)
phone_verified_at
phone_verification_method = kakao_otp | kakao_login | sms_fallback
identity_verified_at = NULL unless separate strong identity verification occurred
```

### Verification challenge persistence

```text
challenge_id
signup_session_ref
email_contact_ref
phone_contact_ref
network_ref
channel
otp_digest
issued_at
expires_at
resend_not_before
attempts_used
max_attempts
generation
state
```

Do **not** persist raw OTP.

### Rate budget persistence

Maintain independent counters/windows for:

```text
signup session
phone contact ref
network ref
```

Do not use raw phone/IP values as model-facing rate keys.

## Development integration

Development/test flow:

```text
DanjiOn signup backend
    -> Padiem Control Plane OTP core
    -> FakeKakaoOtpInbox(test_mode=True)
```

Automated test code may obtain the OTP via the explicit test fixture to simulate the user receiving KakaoTalk.

Do not create a public `/debug/otp` endpoint and do not log OTPs.

## Production integration later

Replace only the transport:

```text
FakeKakaoOtpInbox
      ↓
RealKakaoAlimTalkAdapter
```

Keep the Control Plane challenge/verification contract and DanjiOn signup UI unchanged.

Real Kakao activation requires separate:

- Kakao business/channel setup;
- official dealer/provider selection where applicable;
- approved informational OTP template;
- provider credentials in trusted secret authority;
- live delivery canary;
- cost/commercial approval.

SMS remains optional backend fallback only. Do not expose SMS UI unless product policy changes later.

## Error mapping recommendation

Do not expose sensitive internal distinctions unnecessarily. Map internal failures to bounded UX states such as:

```text
VERIFICATION_CODE_INVALID
VERIFICATION_CODE_EXPIRED
VERIFICATION_LOCKED
RESEND_TOO_SOON
TOO_MANY_REQUESTS
VERIFICATION_REQUIRED
```

Account/phone existence should not be disclosed through different error wording during unauthenticated signup where that could enable enumeration.

## Security requirements

- server-generated six-digit OTP;
- HMAC digest with server-held pepper, not plain OTP hash;
- short expiry;
- one-time challenge consumption;
- failed-attempt lockout;
- resend supersedes old challenge;
- rate-limit session/phone/network dimensions;
- raw email/phone/OTP absent from model-safe state;
- no OTP in application logs/analytics;
- verification receipt bound to exact signup session and contact refs;
- `phone_verified` is contact possession, not legal identity verification.

## DanjiOn acceptance checklist

```text
UI_EMAIL = YES
UI_PHONE = YES
UI_VERIFICATION_CODE = YES
UI_SMS_SELECTOR = NO
DEFAULT_DEV_TRANSPORT = KAKAO_SIMULATOR
DANJION_OTP_ALGORITHM_FORK = NO
CONTROL_PLANE_CONTRACT_REUSED = YES
RAW_OTP_DB = NO
RAW_OTP_LOG = NO
RAW_PHONE_MODEL_CONTEXT = NO
OTP_EXPIRY = YES
OTP_LOCKOUT = YES
OTP_RESEND_SUPERSEDES_OLD = YES
OTP_RATE_LIMIT = YES
SIGNUP_REQUIRES_EXACT_VERIFICATION_RECEIPT = YES
PHONE_VERIFIED_EQUALS_LEGAL_IDENTITY = NO
REAL_KAKAO_SEND = SEPARATE_GATE
SMS_UI = NO
```
