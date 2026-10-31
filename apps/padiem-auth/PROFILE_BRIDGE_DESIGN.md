# B62 verified profile bridge — draft design

Status: design only. No runtime implementation and no deployment. Chat shared login must remain disabled until the implementation, account comparison and integration validation are complete.

## Existing behavior and gap

The Google callback requests `openid` and verifies the Google ID token, then retains only `sub` internally. The token response contains the Padiem canonical account ID, not the verified email or profile. Chat's legacy Google callback upserts a profile using verified Google user information and performs existing signup notification and account linking. A common-auth-only new account cannot currently complete that path.

The shared account registry currently returns an existing fingerprint mapping before resolving a product link. Consequently an account first seen by another product may lack a B62 reverse mapping. This must be fixed with a server-side, idempotent authority operation that verifies the returned canonical subject is the existing subject; conflicts and blocked accounts fail closed. Never use email to merge accounts.

## Contract

- Restrict profile disclosure by an explicit per-client claim allowlist. Only B62 opts in to `email`, `email_verified`, `name`, and `picture`; clients without the setting receive no profile. Strictly validate configuration and reject unknown claims. This minimizes disclosure for other products.
- Request the Google `email` and `profile` scopes only for a client configured to receive those claims. Obtain claims from the Google ID token after signature, issuer, audience, nonce and expiry validation. Require a nonempty verified email (`email_verified` is boolean true); bound lengths and validate optional fields. Invalid or unavailable verified profile fails closed for this opt-in flow.
- Bind the profile to the short-lived one-use authorization code and the intended client, callback and PKCE challenge. On authenticated server-to-server `/token` authorization-code exchange, return the allowed claims with the canonical Padiem account ID. Do not return Google `sub`, Google credentials, profile to the browser callback, refresh responses, URLs, logs, or unrelated clients. Clear profile material on code consumption and on expiration, including abandoned codes. The implementation must account for existing Durable Object schema and encrypt stored profile data or otherwise establish a bounded, non-logging transient storage design.
- Chat verifies the signed access token and binds the response account ID to its verified `accountId` before consuming profile fields. Resolve an existing B62 link through the identity authority. For a genuinely new link, create or update the Chat profile keyed by canonical account identity using existing signup defaults, existing notification behavior and identity authority; preserve `free` default and never grant administrator rights. A mismatch, ambiguous link, missing verified claims, failed authority or storage operation must not issue a Chat session. Existing legacy accounts use verified identity mapping, never email matching alone.
- Keep an idempotent retry story for failures between code consumption, authority linking, profile creation and session creation. Avoid changing existing product user IDs or workspace ownership for existing users. Establish the actual workspace creation semantics before implementing that part.

## Required tests before review

1. Verified profile is available only to opted-in B62 during one-time code exchange; omitted for unlisted clients and refresh, absent from browser redirects and logs, and raw Google subject never leaves the authority.
2. Bad issuer, audience, nonce, signature, expired token, missing or unverified email, malformed profile, invalid allowlist and nonmatching client/PKCE are rejected without session/profile creation.
3. Repeat or abandoned code cannot disclose stale profile; schema upgrade works with an existing Durable Object; cleanup and retry behavior are demonstrated.
4. New Chat user, returning Chat user, existing LoveTree-first user, existing Chat mapping, blocked account and conflicting mapping: no duplicate account, no cross-user link, same free default and signup notification semantics as legacy.
5. Actual Worker/Pyodide integration confirms the response and feature-off path; test against #6282 after #6267 and callback registration are merged. Neither CI nor the design authorizes Chat rollout.
