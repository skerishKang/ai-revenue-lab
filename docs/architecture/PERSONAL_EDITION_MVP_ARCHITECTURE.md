# Personal Edition MVP Architecture

## 1. Purpose

This document defines the smallest technical architecture needed to test the first revenue experiment selected in ADR-0001.

The architecture must support one complete loop:

```text
user input
→ editorial plan
→ personal edition
→ review and publication
→ reader feedback
→ materially changed next edition
→ experiment accounting
```

The system is intentionally optimized for low cash cost, low implementation complexity, strong auditability, and suitability for narrowly instructed free-model workers. It is not intended to be a general multi-product platform.

## 2. Architecture decision

Use a single server-rendered Python application.

Initial technical choices:

- Python 3.12 or newer;
- FastAPI for HTTP routes and form handling;
- Jinja2 for server-rendered edition pages;
- Pydantic models for input and generated-output validation;
- standard-library `sqlite3` for persistence;
- HTTPX for external model-provider calls;
- pytest for automated tests;
- plain CSS with no required JavaScript build step;
- Uvicorn for local execution;
- one replaceable AI-provider adapter boundary.

No frontend framework, ORM, distributed queue, vector database, scheduler, or container orchestration is required for the first pilot.

## 3. Why this stack

### 3.1 One process is sufficient

The first experiment involves a small number of invited participants, manually triggered generation, and text-first output. A distributed architecture would add failure modes without improving the first learning objective.

### 3.2 Server-rendered pages preserve the product distinction

The product must look and feel like a letter or magazine rather than a chat window. Jinja templates and structured page data are sufficient to create a polished mobile-readable edition without introducing a separate frontend application.

### 3.3 SQLite is appropriate for the pilot

The pilot needs durable local records, transactional updates, inspectable data, and easy deletion. A file-backed SQLite database is sufficient for the expected scale and can later be migrated if concurrent production use requires it.

Transactions must be explicit in the repository layer. Application services must not scatter ad hoc SQL or commits across route handlers.

### 3.4 Structured model output is mandatory

Generated prose must pass through Pydantic validation before publication. Providers are asked for structured JSON, not arbitrary HTML. The application renders validated fields into templates.

### 3.5 Provider replacement is a first-class requirement

HY3 is the initial free-model candidate, not a permanent dependency. Product services call an internal provider interface. Provider names, model names, base URLs, and credentials remain in environment or deployment configuration.

## 4. System boundary

### In scope

- create a pilot participant;
- accept user-supplied text;
- store prior editions and feedback;
- generate an editorial plan;
- generate a structured edition draft;
- validate the draft against supplied material and prior state;
- allow manual review and publication;
- display the edition through a private participant link;
- collect structured and free-form feedback;
- generate a next edition using prior feedback;
- record free and paid model usage, latency, errors, and human correction time;
- delete a participant's pilot data.

### Out of scope

- global source collection;
- live web research;
- public registration;
- social login;
- recurring payment integration;
- email automation;
- push notifications;
- native mobile applications;
- image generation;
- multiple personal publications per participant;
- autonomous long-term memory beyond stored pilot records;
- public sharing and social feeds;
- concurrent high-volume generation;
- complex role-based administration.

## 5. Application structure

Recommended initial repository layout:

```text
app/
├─ __init__.py
├─ main.py
├─ config.py
├─ domain/
│  ├─ models.py
│  ├─ enums.py
│  └─ errors.py
├─ db/
│  ├─ connection.py
│  ├─ migrations.py
│  └─ repositories.py
├─ ai/
│  ├─ base.py
│  ├─ mock.py
│  ├─ openai_compatible.py
│  └─ prompts/
│     ├─ editorial_plan.md
│     ├─ edition_draft.md
│     └─ review.md
├─ services/
│  ├─ participant_service.py
│  ├─ generation_service.py
│  ├─ validation_service.py
│  ├─ publication_service.py
│  └─ experiment_service.py
├─ routes/
│  ├─ participant.py
│  └─ admin.py
├─ templates/
│  ├─ base.html
│  ├─ input_form.html
│  ├─ edition.html
│  ├─ feedback_form.html
│  └─ admin_review.html
└─ static/
   └─ app.css

migrations/
├─ 0001_initial.sql
└─ 0002_indexes.sql

tests/
├─ fixtures/
├─ unit/
├─ integration/
└─ snapshots/

scripts/
├─ create_participant.py
├─ generate_pending.py
└─ delete_participant.py

pyproject.toml
.env.example
README.md
```

The free implementation worker may adjust file names when necessary, but it must preserve the boundaries between routes, domain validation, persistence, provider access, and generation services.

## 6. Core domain records

### Participant

Stores pilot-level preferences and access control.

Required fields:

- internal identifier;
- display name or pseudonym;
- hashed private access token;
- preferred language;
- tone preference;
- length preference;
- active or deleted status;
- created and updated timestamps.

Do not store unnecessary demographic data.

### InputRecord

Represents material intentionally supplied for an edition.

Required fields:

- participant identifier;
- sequence number;
- raw text;
- normalized text;
- submitted timestamp;
- consent confirmation;
- deletion timestamp when applicable.

### Edition

Represents a generated and optionally published personal edition.

Required fields:

- participant identifier;
- edition number;
- prior edition identifier where applicable;
- input record identifier;
- generation status;
- validated structured content;
- rendered title;
- draft, review, and publication timestamps;
- human correction duration;
- reviewer notes;
- published or rejected state.

### Feedback

Required fields:

- participant identifier;
- edition identifier;
- structured direction choices;
- optional selected section;
- free-form instruction;
- submitted timestamp;
- whether the next edition visibly applied the feedback.

### GenerationRun

Required fields:

- task type;
- provider identifier;
- advertised model identifier;
- verified upstream status when known;
- free, paid, local, or unknown cost class;
- prompt version;
- started and completed timestamps;
- latency;
- success or failure;
- response validation status;
- input and output token counts when available;
- retry count;
- error category;
- human correction minutes attributable to the run.

Credentials and raw authorization headers must never be stored.

## 7. Access model

The pilot does not require a full authentication system.

Each participant receives an unguessable private token. Only a cryptographic hash of that token is stored. Participant URLs may use the raw token as a path or query credential during the pilot.

Requirements:

- token generation uses a cryptographically secure random source;
- token comparison is performed safely;
- participant pages are excluded from indexing;
- responses containing private content use restrictive cache headers;
- no participant list is publicly accessible;
- administrative generation and review routes require a separate environment-configured admin secret or local-only execution;
- logs must not record raw private tokens or full user input.

This access mechanism is acceptable only for a small invited pilot. It is not a substitute for a full production authentication design.

## 8. AI provider interface

Application services depend on a provider protocol rather than a named vendor.

Minimum conceptual interface:

```python
class AIProvider(Protocol):
    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult: ...
```

`ProviderResult` must include:

- validated or raw response payload;
- provider and model identifiers;
- latency;
- usage metadata when available;
- retries;
- request identifier;
- error information;
- cost classification.

Initial implementations:

### MockProvider

Used for deterministic unit and integration tests. It returns fixture-controlled structured responses and simulates failures.

### OpenAICompatibleProvider

Used for providers exposing a compatible chat-completions or response endpoint. Base URL, model, key, and timeout are configuration values.

Additional CLI or custom provider adapters may be added only when a tested runtime need exists. Provider-specific response parsing must remain inside its adapter.

## 9. Generation pipeline

Generation must use at least two logical stages.

### Stage 1: editorial plan

The model receives:

- segmented user input with stable segment identifiers;
- selected prior-edition facts and themes;
- explicit feedback;
- tone and length preferences;
- prohibited interpretations.

It returns a structured EditorialPlan containing:

- central theme;
- section plan;
- factual claims tied to input segment identifiers;
- clearly labeled interpretations;
- feedback actions to apply;
- continuity references;
- excluded or uncertain material;
- next-edition question proposal.

### Stage 2: edition draft

The model receives the validated EditorialPlan and produces structured EditionContent.

It must not receive permission to add new personal facts. Each section references the plan items and input segments on which it is based.

### Stage 3: deterministic validation

The application rejects a draft when:

- required fields are missing;
- section or total length is outside configured bounds;
- referenced input segments do not exist;
- the draft contains unsupported named persons, places, dates, or amounts;
- the draft presents an interpretation as a direct user statement;
- prohibited advice categories are detected;
- required feedback action is absent from a follow-up edition;
- raw HTML or scripts appear in generated fields.

### Stage 4: optional model review

A free secondary model may review source faithfulness and feedback application. Model review can add warnings but cannot bypass deterministic validation.

### Stage 5: human pilot review

During the first paid pilot, every edition remains `pending_review` until a human approves or edits it. The system records correction time and material changes.

Automatic publication is a later decision based on measured quality.

## 10. Rendering rule

The model never produces complete HTML.

EditionContent is rendered through trusted Jinja templates. Generated text is escaped by default. Formatting is limited to predefined structured fields such as:

- title;
- deck;
- opening paragraph;
- ordered sections;
- highlighted insight;
- continuity note;
- next-edition prompt.

The visual design should communicate a personal letter or compact editorial magazine. The first version prioritizes typography, spacing, hierarchy, and mobile readability over animation or complex interactivity.

## 11. Initial routes

Participant routes:

```text
GET  /p/{token}
GET  /p/{token}/input
POST /p/{token}/input
GET  /p/{token}/editions/{edition_number}
POST /p/{token}/editions/{edition_number}/feedback
GET  /p/{token}/history
POST /p/{token}/delete-request
```

Administrative routes or scripts:

```text
POST /admin/participants
POST /admin/generate/{participant_id}
GET  /admin/review/{edition_id}
POST /admin/review/{edition_id}/publish
POST /admin/review/{edition_id}/reject
```

Administrative actions may initially be command-line scripts rather than browser routes. The implementation should choose the smaller reliable option.

## 12. Database transaction boundaries

Each service operation uses one explicit transaction where practical.

Examples:

- input submission and sequence allocation;
- generation-run creation and status transition;
- edition draft plus associated run metadata;
- feedback submission;
- publication approval;
- participant deletion or anonymization.

Routes do not call `commit()` directly. Repository or unit-of-work helpers control commit and rollback.

## 13. Error behavior

Provider and validation failures must not expose provider details or user text to the participant.

Required states:

- `input_received`;
- `generation_pending`;
- `generation_failed`;
- `pending_review`;
- `published`;
- `rejected`;
- `deleted`.

Retries must be bounded. A failed run records its provider, model, stage, error category, and retry count. It must not overwrite the last published edition.

## 14. Configuration

Minimum environment variables:

```env
APP_ENV=development
APP_BASE_URL=http://127.0.0.1:8000
DATABASE_PATH=./data/personal-edition.sqlite3
ADMIN_SECRET=replace-me
AI_PROVIDER=mock
AI_MODEL=mock-personal-edition-v1
AI_BASE_URL=
AI_API_KEY=
AI_TIMEOUT_SECONDS=120
PROMPT_VERSION=personal-edition-v1
```

`.env.example` contains placeholders only. Real credentials remain in local or deployment secrets.

## 15. Testing strategy

### Unit tests

- Pydantic schema validation;
- participant token hashing and comparison;
- input segmentation;
- unsupported-claim detection;
- feedback-action validation;
- provider error normalization;
- experiment metric calculations.

### Integration tests

Using a temporary SQLite database and MockProvider:

- create participant;
- submit first input;
- generate and publish first edition;
- submit feedback;
- generate second edition;
- verify feedback is represented;
- verify history access isolation;
- delete participant data;
- simulate provider timeout and invalid JSON.

### Presentation tests

- edition page renders without raw JSON or HTML injection;
- required sections appear;
- mobile viewport remains readable;
- participant pages contain no-index and restrictive caching directives.

No test may require a paid or external model call by default.

## 16. Local commands expected from implementation

The finished scaffold must provide documented equivalents of:

```bash
python -m venv .venv
python -m pip install -e '.[dev]'
python -m app.main
pytest
```

The exact local run command may use Uvicorn directly, but there must be one clear command for running and one for validating the repository.

## 17. Initial deployment

The first pilot may run locally for development and on the existing Oracle Cloud server for invited access.

Deployment should remain a single application process plus one SQLite database file. A reverse proxy and HTTPS may be added for remote pilot access. Containerization is optional and must not delay the first working loop.

The database file and participant editions require encrypted backups or a documented no-backup policy during the smallest test. Public search indexing must remain disabled.

## 18. Exit criteria for the architecture phase

This architecture is considered implemented when:

- the complete two-edition feedback loop works with MockProvider;
- HY3 or another approved free provider can replace MockProvider through configuration;
- no product service imports a provider-specific client directly;
- every generated edition passes structured validation;
- private participant links are isolated;
- pilot economics and correction time are recorded;
- tests run without external AI access;
- a new free-model worker can reproduce the environment from repository instructions.

## 19. Future migration triggers

Do not migrate merely because a larger architecture seems more professional.

Consider PostgreSQL, background queues, full authentication, object storage, or a frontend application only when measured requirements appear, such as:

- concurrent generation causes request blocking;
- SQLite write contention occurs;
- participant count or access requirements exceed token links;
- automated delivery becomes essential;
- multiple products need shared identity and data;
- large media assets are introduced;
- production availability requirements justify additional complexity.
