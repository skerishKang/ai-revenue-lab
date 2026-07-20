# World Feed — Phase 1 MVP

Status: **Active implementation (Issue #36)**

World Feed turns abundant free AI inference into a different personalized
"world edition" for each reader, starting from **synthetic source cards only**.
No live crawling, no web calls, and no claim of current real-world facts.

## Product loop

```
synthetic source cards
  -> normalize / validate provenance & state
  -> deterministic personalized ranking
  -> first Korean microbrief
  -> persisted explicit feedback
  -> materially changed second microbrief
  -> pending_review
  -> privacy-safe pilot evidence
```

Initial hypothesis (synthetic, no payment integration): one sample free,
seven adapted microbriefs for KRW 3,900. No claim of actual users, demand,
payment, or revenue.

## What this workspace contains

- `app/` — FastAPI + SQLite implementation, fully independent of sibling apps.
- `migrations/` — versioned SQLite schema (`001_initial.sql`).
- `tests/` — unit + integration tests using temporary file-backed SQLite and
  zero network.
- `PRODUCT_CONTRACT.md` — the local product contract.

## Design rules enforced by code

- **Source states**: `single_source`, `multi_source`, `conflicting`,
  `superseded`, `withdrawn`. Withdrawn/superseded are never selected;
  conflicting carries an explicit uncertainty penalty.
- **No duplicate canonical slots**: `canonical_events.canonical_key` is
  UNIQUE, so multiple source cards for one event occupy a single slot.
- **Feedback exactly once**: `feedback.idempotency_key` is UNIQUE; the second
  brief is generated at most once per feedback and the feedback is marked
  applied exactly once.
- **Atomic multi-step writes**: service operations run inside explicit
  transactions; a failure rolls back and never overwrites the last valid brief.
- **Bounded retries + exact accounting**: generation runs record
  provider/model, task, prompt version, latency, retry count, token usage,
  validation status, and a privacy-safe error category. Retried usage and
  latency are aggregated correctly.
- **No automatic publication**: every generated brief is `pending_review`.
- **Privacy-safe evidence**: pilot evidence stores only anonymous tokens and
  evidence type; no personal identifiers.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

The default provider is the network-free `MockProvider` (model
`mock-world-feed-v1`); `/health` reports the active provider and model.
