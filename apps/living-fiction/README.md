# Living Fiction

Status: **Phase 1 implementation — pending human review**

Living Fiction tests whether AI can sustain a shared narrative canon while
rapidly producing reader-responsive personal branches that visibly reflect
explicit reader choices — without mutating shared canon or auto-publishing.

## Product principle

A common canon preserves shared discussion and fandom. Optional
reader-responsive personal branches provide personalization without turning
every reader's experience into an unrelated work. Canon is immutable once
accepted; branches may add branch-only facts but cannot rewrite canon.

## Current work (Phase 1)

- product and narrative contract approved for implementation;
- independent FastAPI package under `apps/living-fiction/`;
- SQLite-backed canon/branch/episode/choice repositories;
- provider-neutral `AIProvider` protocol with deterministic `MockProvider`;
- deterministic continuity, IP, safety, and markup validators;
- file-backed canon episode and personal branch generation flows;
- all generated episodes remain `pending_review` until explicit human
  publication.

## Running

```bash
cd apps/living-fiction
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
uvicorn app.main:app --reload
```

See `PRODUCT_CONTRACT.md` for the full product/narrative/canon/branch
contract and `NARRATIVE_CONTRACT.md` for the design-track narrative contract.
