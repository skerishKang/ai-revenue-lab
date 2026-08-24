# B60 official-source intake contract (V10)

Issues: #654, #682  
Source-intake foundation: #655

This module is the read-only intake and human-review boundary between official web sources and B60 snapshots.

## Safety / truth invariant

`FETCHED` or `EXTRACTED` does **not** mean verified.

```text
OFFICIAL URL
  ↓ fetch
FETCHED evidence envelope + SHA-256
  ↓ extract known claims
NEEDS_REVIEW candidate
  ↓ review packet (old value / observed value / official evidence)
EXPLICIT HUMAN approve | reject
  ↓ approved candidates only
SNAPSHOT PROPOSAL + FIELD-LEVEL CHANGE LEDGER
  ↓ STOP
SEPARATE HUMAN PUBLICATION AUTHORITY REQUIRED
```

There is no code path from network fetch directly to `VERIFIED_OFFICIAL_WEB`, and the review/promotion CLI never edits the product snapshot or deploys the site.

## Field-level verification provenance

Promotion records exactly which fields were supported by approved evidence:

- `fieldVerification.<field>` contains official-source status, source id, observed time, review time, and evidence SHA-256 for each freshly verified field;
- `carriedForwardFields` lists pre-existing non-metadata fields that were not observed in the approved candidates;
- `verificationScope = FULL_RECORD` only when no claim-bearing base fields were carried forward;
- otherwise `verificationScope = OBSERVED_FIELDS_ONLY` and the record-level status is `PARTIALLY_VERIFIED_OFFICIAL_WEB`.

Example: if a fresh official page confirms `freeLabel` but does not expose the historical `price`, the old price may remain in the proposal for continuity, but `price` appears in `carriedForwardFields`, has no `fieldVerification.price`, and cannot appear as a fresh verified change in the Change Ledger.

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

## Human review packet

`review-promotion.cjs` builds a deterministic packet keyed to the candidate set and source snapshot. Each reviewable candidate shows:

- current snapshot value;
- newly observed official-source value;
- changed / unchanged status;
- source URL, evidence SHA-256 and excerpt;
- required-evidence blockers;
- fields that would be carried forward without fresh verification.

Every `NEEDS_REVIEW` candidate must receive exactly one explicit `approve` or `reject` decision in a promotion run. Silent omission is rejected.

## Snapshot proposal and Change Ledger

A successful promotion produces artifacts only:

- `review-packet.json`
- `review-packet.md`
- `reviewed-candidates.json`
- `snapshot-proposal.json`
- `change-ledger.json`

Both proposal and ledger carry:

```text
publishAuthorized = false
publicationAuthority = HUMAN_EXPLICIT_PUBLISH_REQUIRED
```

The Change Ledger includes only fields present in fresh `fieldVerification`. Carried-forward fields are excluded from verified changes by construction. Re-verified but unchanged fields are listed separately from actual changes.

## Source manifest

Initial primary-source pages:

- Vercel AI Gateway / GLM 5.2;
- Google Gemini API pricing;
- Cloudflare Workers AI pricing;
- Groq rate limits + billing FAQ;
- OpenRouter pricing + free router.

A source matcher finding a claim only produces an observation. It is not publication authority.

## Intake CLI

```bash
node collector/run-intake.cjs
node collector/run-intake.cjs --source vercel-glm52-model
node collector/run-intake.cjs --out ./tmp/b60-candidates.json
```

The intake CLI emits candidates with `publicationAuthority = REVIEW_REQUIRED` and never promotes them into the product catalog.

## Review / promotion CLI

Create a human-readable review packet directly against the current JS snapshot:

```bash
node collector/run-review.cjs packet \
  --candidates ./tmp/b60-candidates.json \
  --snapshot ../data/snapshots.js \
  --out ./tmp/review-packet.json \
  --markdown ./tmp/review-packet.md
```

After a human creates an explicit decisions JSON using the packet candidate ids:

```bash
node collector/run-review.cjs promote \
  --candidates ./tmp/b60-candidates.json \
  --snapshot ../data/snapshots.js \
  --decisions ./tmp/decisions.json \
  --out-dir ./tmp/promotion \
  --date 2026-08-24 \
  --captured-at 2026-08-24T06:00:00.000Z
```

This command does **not** write `data/snapshots.js` and does **not** publish or deploy anything.

## Contract tests

```bash
node --test collector/intake-core.test.cjs collector/review-promotion.test.cjs
```

The suites are deterministic and use no live network. They cover explicit decisions, rejection, required-evidence blocking, carried-forward semantics, verified field changes, re-verified unchanged fields, and the no-auto-publish boundary.

## Non-goals

No scheduler, Neon, auth, alerting, API-key vault, model execution, billing, automatic publication, or production deployment is introduced in V10.
