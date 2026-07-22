# Living Travel

Status: **Phase 1 MVP — approved product contract and isolated generation scaffold**

## What is this

Living Travel is a recurring personal travel publication. A reader receives a polished edition, reacts to it, and receives a materially adapted next edition.

## First experiment

- **Destination:** Busan (synthetic fixtures)
- **Reader:** Korean solo traveler, 2-night domestic trip
- **Edition style:** calm, neighborhood-oriented, food-focused
- **Revenue hypothesis:** one free sample + three adapted editions for KRW 4,900

## Architecture

- **Framework:** FastAPI with `/health` endpoint
- **Database:** SQLite with idempotent migrations
- **AI boundary:** Protocol-based provider with network-free MockProvider
- **Pipeline:** plan → draft → validate → persist → pending_review
- **Validation:** source references, information class metadata, markup rejection, duplicate ID detection

## Directory structure

```
apps/living-travel/
├── app/              # Application package
│   ├── domain/       # Models and enums
│   ├── ai/           # Provider protocol + MockProvider
│   ├── pipeline/     # Generation service, prompts, validators, markup
│   ├── config.py     # Settings
│   ├── db.py         # SQLite connection + migrations
│   ├── factory.py    # FastAPI factory
│   └── main.py       # Entry point
├── migrations/       # SQL migration files
├── tests/
│   ├── unit/         # Domain, validator, markup, provider tests
│   ├── integration/  # Repository, pipeline, persistence tests
│   └── fixtures/     # Synthetic Busan fixtures
└── pyproject.toml
```

## Running

```bash
cd apps/living-travel
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Key design decisions

- No network calls in any test or production code path
- All travel data is synthetic with explicit provenance markers
- `time_sensitive` items require `as_of_date`, `source_ref`, `confidence`, and `verify_before_use=true`
- Generation remains `pending_review` — no automatic publication
- Conceptual sibling of Personal Edition; no shared code
