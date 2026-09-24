# Technology Adoption Before Custom Build Policy

- Status: **CANONICAL REPOSITORY OPERATING POLICY**
- Effective: 2026-09-25
- Applies to: new capabilities, substantial subsystem expansion, new parsers/runtimes/providers, document/media processing, agent/runtime infrastructure, and other commodity technology surfaces.
- Related: `AI_DEVELOPMENT_OPERATING_POLICY.md`, `EVIDENCE_REQUIREMENTS.md`, `../internal-platform/AI_ADOPTION_PLAYBOOK.md`, Issue #2996.

## 1. Purpose

AI Revenue Lab exists to ship useful products quickly and economically. It is not a research program whose default goal is to reimplement mature commodity technology.

For a new capability, the default order is:

```text
SEARCH
→ REUSE_INTERNAL
→ BUY
→ ADOPT
→ ADAPT
→ SIDECAR / LOCAL_SERVICE
→ BUILD_FROM_SCRATCH
```

Custom implementation is the last normal option, not the first.

The repository should own Padiem product authority, policy, identity, approvals, provenance and user-facing contracts. It does not need to own every OCR engine, PDF renderer, parser, browser runtime, sandbox, vector implementation, media codec, scheduler primitive, or similar commodity mechanism.

## 2. Mandatory technology landscape gate

Before substantial new implementation begins, the work order records:

```text
LANDSCAPE_SCAN_REQUIRED=YES/NO
INTERNAL_REUSE_AUDITED=YES/NO
OSS_AUDITED=YES/NO
COMMERCIAL_OPTIONS_AUDITED=YES/NO
MANAGED_SERVICE_OPTIONS_AUDITED=YES/NO

CANDIDATES_REVIEWED=
SHORTLIST=
SELECTED_APPROACH=

WHY_NOT_BUY=
WHY_NOT_ADOPT=
WHY_NOT_ADAPT=
WHY_NOT_SIDECAR=
BUILD_FROM_SCRATCH_JUSTIFIED=YES/NO
```

`LANDSCAPE_SCAN_REQUIRED=NO` is allowed for bug fixes, tiny glue code, already-decided implementation slices, or work whose technology choice is already fixed by an accepted parent decision. The reason must be stated.

A worker must not start a substantial custom implementation merely because no equivalent already exists inside this repository.

## 3. Search scope

A useful landscape scan considers, as applicable:

- existing AI Revenue Lab / Padiem components;
- official open-source projects;
- actively maintained community projects with strong adoption;
- commercial SDKs;
- paid APIs;
- self-hosted commercial products;
- managed services;
- reference implementations and research projects.

Paid options are valid. A recurring fee or commercial license is not by itself a rejection reason. Compare total engineering time, operating cost, quality, reliability, support, privacy, lock-in and time-to-product.

## 4. Search breadth and speed

Research must accelerate delivery, not become a new form of analysis paralysis.

Default scan:

```text
CREDIBLE_CANDIDATES=5..12 when the ecosystem is broad
SHORTLIST_MAX=3
ONE_RECOMMENDED_APPROACH=REQUIRED
```

Do not exhaustively audit hundreds of repositories before implementation. Stop when the evidence is sufficient to make a reversible decision.

For urgent P0 work, parallelize landscape research with architecture/current-source audit. Keep the result on the parent issue unless a genuinely independent long-lived authority boundary requires another issue.

## 5. Adoption modes

Classify each serious candidate as one of:

```text
BUY
ADOPT
ADAPT
EMBED
SIDECAR
LOCAL_SERVICE
MANAGED_SERVICE
SANDBOX_JOB
REFERENCE_ONLY
REJECT
```

Prefer the least custom code that preserves the required product contract.

## 6. Product authority vs implementation dependency

The non-duplication invariant is:

```text
SECOND_PRODUCT_AUTHORITY=0
```

Padiem must not create conflicting authorities for:

- tenant/workspace identity;
- role/membership;
- approval/continuation;
- secrets/credentials;
- billing/entitlements;
- audit/provenance;
- external write/send authorization;
- canonical product state.

However, an adopted OCR/document/parser/runtime project may internally contain several parsers, decoders, models, native libraries or helper services. That internal implementation complexity is not automatically a forbidden "second authority" when it is behind one reviewed Padiem adapter/boundary.

Rules such as `SECOND_PDF_PARSER=0`, `SECOND_IMAGE_DECODER=0` or similar historical locks must be interpreted as **no competing Padiem-facing authority**, not as a blanket ban on transitive internals of an adopted project.

When a project would bypass the Padiem boundary and independently make product-policy decisions, it is a duplicate authority and must be rejected or wrapped so that Padiem remains authoritative.

## 7. License and commercial posture

Software license, model/weight license, dataset/provenance terms and redistribution rights are separate questions.

```text
SOFTWARE_LICENSE != MODEL_ARTIFACT_LICENSE
OPEN_SOURCE_CODE != AUTOMATIC_MODEL_REDISTRIBUTION_RIGHT
```

If terms are unclear:

```text
UNRESOLVED_LICENSE
→ inspect authoritative upstream terms
→ inspect artifact/model terms
→ contact vendor/upstream when material
→ evaluate commercial license / paid API / self-host license
→ compare alternatives
→ decision
```

"License unresolved" may block implementation of that candidate, but it must not automatically end the capability search when alternative licensing or commercial procurement is realistic.

Record material attribution, notice, source-disclosure, copyleft, model, dataset and commercial-use obligations before adoption.

## 8. Supply-chain and runtime review

Before adoption, evaluate only the dimensions material to the capability:

- immutable tag/commit/version;
- maintainer/project authority;
- package/model artifact hashes where practical;
- dependency/native-binary footprint;
- install-time and runtime network;
- secret handling;
- data egress and privacy;
- sandbox/process isolation;
- timeout/kill/resource bounds;
- update/rollback strategy;
- Windows/Linux/cloud compatibility;
- model/artifact acquisition;
- vulnerability and provenance posture;
- license/commercial terms.

Do not install large dependencies, pull models, or mutate Production merely to perform the first landscape scan. After a candidate is selected, a bounded evaluation/prototype may install or download artifacts under the work order.

## 9. Build-from-scratch gate

Custom implementation is justified when one or more are demonstrated:

- no credible existing option satisfies the product contract;
- available options cannot meet security/privacy/authority requirements;
- licensing/commercial terms are unacceptable after reasonable investigation;
- total cost of ownership is materially worse;
- required latency/offline/resource constraints cannot be met;
- integration cost is higher than a small stable custom implementation;
- the capability is a true Padiem differentiator or product authority.

The work order must record the reason.

"Existing options were not checked" is never sufficient justification.

## 10. Commodity vs differentiating technology

Default **adopt/buy-first** domains include:

- OCR and document parsing;
- PDF/image/media manipulation;
- HWP/HWPX tooling where credible libraries or commercial SDKs exist;
- browser/computer-use runtimes;
- sandbox providers/runtimes;
- vector/search/storage engines;
- standard schedulers/queues;
- speech/vision/media infrastructure;
- connector SDKs/protocol clients;
- common agent/tool frameworks when they fit the product boundary.

Default **Padiem-owned authority** includes:

- product identity and workspace/tenant semantics;
- authorization and approval;
- credential authority;
- billing/entitlement policy;
- audit/provenance;
- canonical run/session/task state;
- external side-effect authorization;
- product-specific user contract.

## 11. Evidence and final review

Implementation reports and CTO final reviews must answer:

```text
TECH_LANDSCAPE_AUDITED=
SELECTED_APPROACH=
ADOPTION_MODE=
UPSTREAM_PIN=
LICENSE_POSTURE=
COMMERCIAL_COST_POSTURE=
DUPLICATE_PRODUCT_AUTHORITY=0
BUILD_FROM_SCRATCH_JUSTIFIED=
```

A PR implementing a substantial new commodity capability without the required landscape/adoption evidence is `NOT_READY` unless the parent issue already contains an accepted decision.

## 12. Issue discipline

Research does not require routine child issues.

Use the capability parent to record:

```text
TECH_SCAN
→ ADOPTION_DECISION
→ IMPLEMENTATION
→ LIVE/PRODUCTION_GATE when separately required
```

Issue #2996 is the cross-project technology/adoption radar and reusable intake index. Capability-specific decisions still belong on their parent issue.

## 13. Operating principle

```text
SEARCH_BEFORE_BUILD=YES
BUY_ADOPT_ADAPT_BEFORE_BUILD=YES
PAID_TECHNOLOGY_IS_VALID=YES
OWN_PRODUCT_AUTHORITY_NOT_EVERY_IMPLEMENTATION=YES
BUILD_FROM_SCRATCH_REQUIRES_REASON=YES
RESEARCH_MUST_BE_TIME_BOUNDED=YES
```

The goal is faster delivery of a trustworthy product, not maximum custom code.
