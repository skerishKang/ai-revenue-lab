# Personal Edition

Status: **Active first revenue experiment**

Personal Edition transforms a user-supplied conversation, note, journal entry, or voice transcript into a polished recurring letter or compact magazine. Explicit feedback must materially change the next edition.

## Current scope

The first paid pilot tests:

```text
user material
→ editorial plan
→ structured personal edition
→ human review
→ private delivery
→ reader feedback
→ visibly adapted next edition
```

## Canonical documents

- `../../docs/decisions/ADR-0001-first-revenue-experiment.md`
- `../../docs/decisions/ADR-0002-product-workspaces.md`
- `../../docs/product/PERSONAL_EDITION_MVP_CONTRACT.md`
- `../../docs/architecture/PERSONAL_EDITION_MVP_ARCHITECTURE.md`
- `../../docs/experiments/HY3_PERSONAL_EDITION_BENCHMARK.md`

## Implementation rule

All product code, tests, configuration examples, scripts, migrations, and product-local fixtures belong in this directory.

The current implementation entry issue is GitHub Issue #3. No real credentials or private pilot material may be committed.

## Local setup

```bash
python3 -m venv /tmp/ai-revenue-lab-personal-edition-venv
source /tmp/ai-revenue-lab-personal-edition-venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run the application

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Run tests

```bash
pytest -q
```

## Configuration

Copy `.env.example` to `.env` and adjust as needed. Defaults use the `mock` provider, which requires no external dependencies.
