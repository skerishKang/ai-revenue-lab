# World Feed — Product Contract (Phase 1 MVP)

This contract is the local source of truth for the World Feed Phase 1 MVP
(Issue #36). It is satisfied entirely by synthetic data; it makes no claim of
current real-world facts, real users, payment, or revenue.

## 1. Scope

Independent FastAPI/Python/SQLite workspace under `apps/world-feed/`. It must
not import sibling apps, modify the repo root, or create shared packages.

## 2. Endpoints & configuration

- `GET /health` → `{status, ai_provider, ai_model}` (env-backed settings).
- Environment variables use the `WORLD_FEED_` prefix
  (`WORLD_FEED_DATABASE_PATH`, `WORLD_FEED_AI_PROVIDER`, `WORLD_FEED_AI_MODEL`,
  `WORLD_FEED_AI_MAX_RETRIES`, `WORLD_FEED_PROMPT_VERSION`,
  `WORLD_FEED_DEFAULT_BRIEF_SIZE`).
- Versioned SQLite migrations in `migrations/`.

## 3. Records (repositories)

1. **source** — validated synthetic source cards.
2. **canonical_event** — deduplicated events (UNIQUE `canonical_key`).
3. **reader** — privacy-safe synthetic profiles (active flag).
4. **feedback** — structured, persisted exactly once (UNIQUE `idempotency_key`).
5. **brief** — microbriefs, always `pending_review`, UNIQUE `brief_number`.
6. **generation_run** — provider/model/task/prompt/latency/retry/token/
   validation/error accounting.
7. **pilot_evidence** — privacy-safe signals (anonymous token only).

## 4. Source-state contract

| State | Selected? | Rule |
|---|---|---|
| `single_source` | yes | one authoritative source |
| `multi_source` | yes | two+ independent sources agree |
| `conflicting` | yes (penalized) | explicit uncertainty note required |
| `superseded` | no | newer record replaced it |
| `withdrawn` | no | cancelled/withdrawn |

Rejected at ingest: unknown provenance, malformed dates, duplicate ids, unsafe
markup. All cards are synthetic (`synthetic_flag` required true).

## 5. Feedback contract

Structured feedback (e.g., increase culture/neighborhood coverage, reduce
promotional entertainment) is applied exactly once to the matching reader and
prior brief. The second brief must materially change while still satisfying
exclusions and source-state rules. A failed generation must not consume
feedback or overwrite the last valid brief.

## 6. Transactions & accounting

- Multi-step writes are atomic; rollback on failure leaves prior state intact.
- Duplicate/retry requests never create duplicate brief numbers or apply
  feedback twice.
- Generation runs accurately capture provider/model, task, prompt version,
  latency, retry count, token usage, validation result, and a privacy-safe
  error category. Retries aggregate usage and latency.

## 7. Privacy

No personal identifiers are stored. Reader profiles contain only interests and
coverage preferences. Pilot evidence uses anonymous tokens. Evidence detail is
length-bounded and redacts email, phone, account/card numbers, credentials,
tokens, API keys, payment references, and private artifact paths. Evidence must
not claim actual payment or revenue; the Phase-1 economic hypothesis is exactly
one free sample plus seven adapted microbriefs for KRW 3,900.

## 7.1 Reader deletion / revocation

`DELETE /readers/{reader_id}` (and `WorldFeedService.delete_reader`) runs as one
transaction that:

- removes personal brief rows for that reader;
- removes feedback rows (including private detail text);
- anonymizes pilot-evidence `reader_id` to a non-reversible `revoked:` token and
  clears detail;
- deletes the reader profile row;
- leaves shared canonical events and source records untouched.

Repeated deletion after close/reopen is idempotent (`already_absent`).

## 8. Acceptance

- fresh external venv, zero network, temporary file-backed SQLite;
- migrations apply and are idempotent;
- package independence (no sibling import);
- reader ownership / inactive behavior;
- all five source states behave per the table;
- first brief is deterministic and `pending_review`;
- persisted-feedback second brief is materially different;
- transaction rollback, idempotency, no-overwrite on failure;
- exact generation accounting;
- privacy-safe evidence;
- file-backed close/reopen persistence;
- `/health` smoke.
