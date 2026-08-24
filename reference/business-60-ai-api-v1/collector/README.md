# B60 official-source intake contract (V9)

Issue: #654  
Parent implementation: #652 / Draft PR #653

This module is the read-only intake boundary between official web sources and B60 snapshots.

## Safety / truth invariant

`FETCHED` or `EXTRACTED` does **not** mean verified.

```text
OFFICIAL URL
  ↓ fetch
FETCHED evidence envelope + SHA-256
  ↓ extract known claims
NEEDS_REVIEW candidate
  ↓ explicit reviewer decision
APPROVED_FOR_SNAPSHOT | REJECTED
  ↓ approved candidates only
snapshot record with field-level verification provenance
```

There is no code path from network fetch directly to `VERIFIED_OFFICIAL_WEB`.

A promotion may preserve older fields from the base record so the snapshot shape remains usable, but those carried-forward fields are never fresh-stamped merely because another field was observed and approved.

## Field-level verification provenance

Promotion records exactly which fields were supported by the approved evidence:

- `fieldVerification.<field>` contains the official-source status, source id, observed time, review time, and evidence SHA-256 for each newly verified field;
- `carriedForwardFields` lists pre-existing non-metadata fields that were not observed in the approved candidates;
- `verificationScope = FULL_RECORD` only when no claim-bearing base fields were carried forward;
- otherwise `verificationScope = OBSERVED_FIELDS_ONLY` and the record-level status is `PARTIALLY_VERIFIED_OFFICIAL_WEB`.

Example: if a fresh official page confirms `freeLabel` but does not expose the historical `price`, the old price may remain in the snapshot for continuity, but `price` appears in `carriedForwardFields`, has no `fieldVerification.price`, and the whole record cannot claim fresh `VERIFIED_OFFICIAL_WEB` status.

## Evidence envelope

Each fetch records:

- source id / signal id / provider;
- requested URL and final URL;
- observed timestamp;
- HTTP status and content type;
- body byte length;
- SHA-256 of the fetched body.

Raw body is held only for extraction in the current process. Candidate output carries the hash and short evidence excerpts instead of silently rewriting facts.

## Review states

- `FETCHED`
- `EXTRACTED` (internal extraction milestone)
- `NEEDS_REVIEW`
- `APPROVED_FOR_SNAPSHOT`
- `REJECTED`

Approval requires an explicit reviewer identity. Required evidence missing from a source blocks approval.

## Source manifest

Initial primary-source pages:

- Vercel AI Gateway / GLM 5.2;
- Google Gemini API pricing;
- Cloudflare Workers AI pricing;
- Groq rate limits + billing FAQ;
- OpenRouter pricing + free router.

The source manifest owns page-specific evidence matchers. A source matcher finding a claim only produces an observation. It is not publication authority.

## CLI

```bash
node collector/run-intake.cjs
node collector/run-intake.cjs --source vercel-glm52-model
node collector/run-intake.cjs --out ./tmp/b60-candidates.json
```

The CLI performs live read-only fetches when network access exists and emits candidates with:

```text
publicationAuthority = REVIEW_REQUIRED
```

It never promotes them into the product catalog.

## Contract tests

```bash
node --test collector/intake-core.test.cjs
```

Tests are deterministic and use mocked HTTP responses; they do not need live network access. The contract suite includes a regression proving that an unobserved historical price cannot become freshly verified when only another field is approved.

## Non-goals

No scheduler, Neon, auth, alerting, API-key vault, model execution, billing, automatic publication, or production deployment is introduced in V9.
