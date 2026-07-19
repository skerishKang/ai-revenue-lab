# Initial Roadmap

## Phase 0 — Project foundation

Goal: establish the project thesis, operating rules, and measurable definition of success before implementation.

Deliverables:

- project vision;
- AI operating model;
- initial product portfolio;
- experiment accounting rules;
- issue and pull-request workflow;
- first MVP selection.

Exit condition:

The repository contains enough information for a free implementation model to execute a narrow issue without redefining the product.

## Phase 1 — Free-model capability baseline

Goal: determine what HY3 and selected fallback models can reliably do in the actual development and runtime environment.

Initial benchmark tasks:

- structured JSON generation;
- source-to-fact extraction;
- Korean and English summarization;
- translation on selected target languages;
- claim-to-source faithfulness review;
- simple code implementation;
- test repair;
- instruction and scope compliance.

Metrics:

- task success rate;
- schema compliance;
- factual additions not present in the source;
- latency;
- quota and failure behavior;
- provider availability;
- human correction time.

Exit condition:

At least one free provider/model combination is approved for a limited production role, and fallback behavior is documented.

## Phase 2 — First thin product loop

Goal: implement one complete loop rather than a broad platform.

Recommended first loop:

1. accept a small set of approved source records or user-provided travel interests;
2. create a structured content object;
3. generate one polished personal edition;
4. collect one explicit user reaction;
5. generate the next edition using that reaction;
6. record AI usage, human time, and user response.

The final choice between World Feed and Living Travel should be made in a dedicated product-decision issue.

Exit condition:

A real user can receive an edition, react, and receive a materially changed next edition.

## Phase 3 — Delivery and habit

Goal: determine whether packaging and delivery timing create more value than immediate chat output.

Capabilities:

- scheduled morning or evening delivery;
- edition history;
- explicit controls for more, less, hide, follow, and change direction;
- simple personalization memory;
- shareable and persistent edition pages.

Metrics:

- edition open rate;
- return rate;
- explicit feedback rate;
- time spent;
- next-edition request rate;
- willingness to subscribe.

Exit condition:

Evidence shows whether users return for the next edition rather than treating the product as a one-time AI answer.

## Phase 4 — Revenue test

Goal: generate direct or attributable revenue with minimal additional infrastructure.

Possible first tests:

- paid personal edition subscription;
- paid destination or story season;
- affiliate conversion;
- paid final PDF or ebook;
- premium branch or special edition.

Required accounting:

- total cash cost;
- paid-model cost;
- free inference volume;
- infrastructure cost;
- human hours;
- gross revenue;
- attributable revenue per 1,000 AI calls;
- revenue per human hour;
- revenue per published edition.

Exit condition:

At least one nonzero payment or attributable conversion is produced and documented.

## Phase 5 — Scale the winning loop

Only after a revenue or strong retention signal should the project invest in:

- broader source collection;
- more model providers;
- richer personalization;
- multiple languages;
- additional product families;
- shared Personal Edition Engine components.

## Non-goals during early phases

- Kubernetes or complex orchestration;
- a complete multi-product platform;
- prebuilding every application directory;
- optimizing for millions of users before one user loop works;
- proving that one specific model is superior;
- hiding paid-model use to preserve an artificial purity claim.

## Decision discipline

Each phase should be represented by GitHub issues with explicit evidence requirements. A phase does not advance because code exists. It advances because the intended user or economic behavior is demonstrated.
