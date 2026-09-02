# Padiem AI Retrieval Consumer Conformance v1

Authority: #1595  
Promotion governance: #1315  
Generic adapter conformance: #1217  
Core context permission: #1313  
Engine projection: #1319

## Purpose

This contract records the reusable composition proven by a real Padiem product
without transferring product-specific semantics into Padiem AI Core.

Canonical composition:

```text
product domain state / retrieval adapter
  -> product-neutral retrieval candidates
  -> Core retrieval trust + bounds
  -> Core Context Permission / Knowledge Boundary
  -> resolve reference bytes for allowed candidate IDs only
  -> Core bounded reference-context assembly
  -> existing Core execution
  -> B14 model/provider execution
```

The order matters. A candidate being relevant, retrieved, or known does not make
it permitted for a model turn.

```text
RETRIEVED != AUTHORIZED
KNOWN != PERMITTED
FILTERED != MODEL_VISIBLE
```

## Ownership

### Product owns

- domain identifiers and ordering;
- domain retrieval implementation;
- product progress/state used to derive a boundary;
- product-specific policy specialization and user-facing refusal copy;
- storage schemas and persistence.

### Core owns

- bounded provider-neutral retrieval contracts;
- retrieved-reference trust classification;
- namespace/budget validation;
- product-neutral context candidates;
- trusted knowledge-boundary enforcement;
- deterministic allowed/filtered projection;
- fail-closed missing-boundary behavior;
- bounded context preparation;
- reusable execution semantics.

### Engine owns

- cross-runtime projection/transport of the accepted Core semantics.

### B14 owns

- inference provider/model registry;
- inference credentials;
- exact route selection, fallback and retry;
- actual model execution.

## Mandatory consumer invariants

A conforming product adapter must prove:

```text
RETRIEVAL_REMAINS_UNTRUSTED_REFERENCE = YES
EXPLICIT_NAMESPACE_SCOPE = REQUIRED
TRUSTED_BOUNDARY = REQUIRED when product policy requires one
USER_SELF_ASSERTED_PERMISSION = CANNOT_WIDEN
PRODUCT_NARROWING = ALLOWED
FILTERED_REFERENCE_BYTES_IN_MODEL_CONTEXT = 0
MISSING_REQUIRED_BOUNDARY = FAIL_CLOSED
ALLOWED_CANDIDATE_IDS = EXACT_REFERENCE_RESOLUTION_SET
DUPLICATE_RETRIEVAL_IDS = FAIL_CLOSED
PUBLIC_DIAGNOSTICS_PRIVATE_CONTEXT_BYTES = 0
PRODUCT_DOMAIN_GRAMMAR_IN_CORE = 0
PRODUCT_STORAGE_SCHEMA_IN_CORE = 0
B14_ROUTE_AUTHORITY = PRESERVED
PROVIDER_SECRET_IN_PRODUCT_CONFORMANCE = 0
```

The package-local executable contract lives in:

```text
packages/padiem-ai-core/tests/test_retrieval_consumer_conformance.py
```

It composes the already-accepted `retrieval.py` and `context_permission.py`
primitives rather than creating a second retrieval runtime or permission engine.

## First Production reference consumer — B61 StoryMemory

B61 is the first accepted Production reference consumer of this complete pattern.
Only sanitized acceptance metadata is recorded here; StoryMemory private source,
corpus bytes, user annotations, hidden prompts and secrets remain outside this
public repository.

Accepted reference evidence:

```text
PRODUCT = B61 StoryMemory
PRIVATE_ACCEPTED_HEAD = e0fc29f0ea7cc4284d8d52afc2d996f5db600905
PRODUCTION_DEPLOYMENT = 4c391152-72ce-4e3b-b44f-f945da7eff67
REAL_UI_PROJECTION_TO_PACKET = PASS
ENGINE_PATH_USED = YES
CORE_PERMISSION_PATH_USED = YES
B14_PATH_USED = YES
FUTURE_KEYWORD_IN_MODEL_CONTEXT = 0
FUTURE_ANNOTATION_IN_MODEL_CONTEXT = 0
PRETRAINED_FUTURE_KNOWLEDGE_LEAKAGE = 0
BROWSER_SECRET_EXPOSURE = 0
```

This reference does **not** mean Core owns StoryMemory concepts such as Bible or
classic-work locators, reading progress, a furthest-read locator, annotation
storage, or co-reader/spoiler UX. B61 derives its domain boundary; Core enforces
the generic permission semantics after adaptation.

## Second-consumer rule

Future products should consume this contract instead of copying B61 mechanics.
If another product needs a new generic invariant, classify it under #1315 before
implementation:

```text
REUSE_CORE
EXTEND_CORE
PRODUCT_ADAPTER
B14_EXECUTION
ENGINE_TRANSPORT
DO_NOT_SHARE
```

Product-specific retrieval ranking, tokenization, locator grammar, UI copy or
storage behavior is not promoted merely because B61 uses it.

## Non-goals

```text
NEW_RETRIEVAL_RUNTIME = NO
NEW_PERMISSION_ENGINE = NO
VECTOR_DATABASE = NO
EMBEDDING_PROVIDER = NO
MODEL_ROUTER = NO
B61_SOURCE_PUBLICATION = NO
B62_MUTATION = NO
ENGINE_MUTATION = NO
B14_MUTATION = NO
PROVIDER_SECRET_MUTATION = NO
PRODUCTION_DEPLOYMENT = NO
```

## Acceptance

```text
PRODUCTION_CONSUMER_RETRIEVAL_CONFORMANCE = PASS
B61_REFERENCE_CONSUMER_RECORDED = YES
EXISTING_CORE_PRIMITIVES_REUSED = YES
SECOND_RETRIEVAL_RUNTIME = NO
SECOND_PERMISSION_ENGINE = NO
FILTERED_CONTEXT_BYTES_MODEL_VISIBLE = 0
MISSING_BOUNDARY_FAIL_CLOSED = YES
PRODUCT_SPECIFIC_SEMANTICS_IN_CORE = 0
B14_EXECUTION_AUTHORITY_PRESERVED = YES
```
