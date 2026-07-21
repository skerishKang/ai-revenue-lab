# Living Fiction Narrative Contract — Phase 1

## 1. Scope

This contract governs the isolated Phase 1 urban-mystery experiment under
`apps/living-fiction/`. It does not share runtime code with Personal Edition,
Living Travel, or any other product. The world, characters, locations, clues,
and episodes are synthetic and must not identify a real person, real company,
copyrighted franchise, or pre-existing fictional character.

## 2. Narrative objects

### Canon

Canon is the shared, human-approved narrative lineage. Generated content is
never canon merely because generation or validation succeeded. A canon episode
must remain `pending_review` until an explicit human publication decision.

### Accepted snapshot

An accepted canon snapshot is an immutable, versioned statement of authoritative
world facts at a known canon episode number. New accepted state requires a new
snapshot version; an accepted snapshot is not edited in place.

### Checkpoint

A checkpoint identifies a position in one accepted canon lineage. It may be
marked compatible for future rejoin, but compatibility alone does not authorize
rejoin. The service must also validate the branch's persisted consequences.

### Personal branch

A personal branch belongs to exactly one active reader and references exactly
one persisted reader choice, one prior published episode, and one canon
checkpoint in the same world. It may add branch-only facts but may not silently
rewrite canon.

### Rejoin

Rejoin is a service-owned state transition. The service loads the branch,
branch episode, source checkpoint, target checkpoint, accepted snapshots, and
persisted unresolved consequences. Rejoin is rejected when lineage is foreign,
the target is incompatible, or unresolved consequences would be erased without
a specific explanation. Repository-level direct mutation is prohibited.

## 3. Phase 1 story loop

1. A human publishes the shared opening canon episode.
2. An active reader submits one explicit choice and an optional short comment.
3. The service binds the request to the persisted reader, choice, published
   prior episode, accepted snapshot, and checkpoint.
4. A provider-neutral plan and draft are generated without trusting caller-
   supplied narrative facts or private text.
5. Deterministic validators enforce structure, reference integrity, safety,
   material reader-input application, and production continuity.
6. Episode creation, branch creation, choice application, and idempotency
   completion commit atomically.
7. The branch remains `pending_review`; no automatic publication or canon
   promotion occurs.

The Phase 1 offer hypothesis is one free canon episode plus four personal branch
episodes offered for KRW 4,900. This is a hypothesis only; the repository must
not claim an actual reader, payment, revenue event, or literary-quality result.

## 4. Authoritative input boundary

For personal branches, callers may provide identifiers but may not define
trusted story state. The service reconstructs authoritative world and canon
state from persisted repositories. Persisted choice text and comment override
caller-supplied copies. Provider output must independently reproduce the bound
reader-input identity and content; the service must not rewrite provider output
to make it pass.

## 5. Continuity rules

A branch is rejected when it introduces any of the following without an
explicit, validated delta and evidence:

- unknown or foreign world, character, location, clue, episode, or checkpoint;
- character movement between disconnected locations;
- knowledge without prior possession, direct observation, a present source
  character, or a referenced clue/scene source;
- injury, possession, status, or relationship changes that contradict the
  accepted snapshot or prior episode;
- resolution or disappearance of a canon clue without an allowed explanation;
- disappearance of a persisted unresolved thread without a recorded resolution;
- mutation of an immutable canon fact;
- reuse of a choice already applied to another branch.

Branch-only facts remain local to the branch unless a separate human-reviewed
canon process explicitly adopts them.

## 6. Idempotency and numbering

An idempotency key is durably bound to reader, choice, prior episode,
checkpoint, world, and operation type. Concurrent calls with the same key must
produce one provider call set and replay one result. Different keys may proceed
independently. Episode numbers are durably reserved inside a SQLite write
transaction before provider work; numbers may have gaps after failure but must
never be reused or duplicated.

## 7. Safety and intellectual property

Recursive validation rejects raw HTML, scripts, iframes, event handlers, unsafe
URLs, prohibited real-person or franchise identifiers, sexual content involving
minors, sexual violence, graphic torture, and instructions facilitating real
harm. These deterministic checks enforce explicit repository contracts; they do
not prove universal originality or literary quality.

## 8. Privacy and deletion

Private reader text is not export-safe evidence. Durable failure records contain
only static error categories and messages. Reader deletion is transactional and
removes or irreversibly anonymizes reader profiles, choices, comments, personal
branches, rejoin records, idempotency bindings, and evidence links. Shared canon
may remain only after personal linkage has been removed.

## 9. Provider and accounting attribution

Generation runs and attempts record the actual instantiated provider, advertised
model, canonical cost class (`free`, `paid`, `local`, or `unknown`), prompt
version, latency, retry count, token usage, validation result, and privacy-safe
error category. `/health` reports the same runtime provider identity rather than
settings labels or enum representations.

## 10. Human-control invariants

- No automatic publication.
- No automatic canon promotion.
- No direct repository bypass for validated rejoin state changes.
- No live external provider call in Phase 1.
- No payment processing, public signup, OAuth, email, social sharing, or
  recommendation feed.
- Every generated episode remains reviewable and reversible before publication.
