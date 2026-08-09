# Proposed Business 21 — Founder Strategy Letter Phase 1 UI

Status: `UI_REVIEW_READY`

This directory contains the static, synthetic Phase 1 visual reference for **Founder Strategy Letter / 대표 전략 편지** under the visual concept **Decision Correspondence / 결정 서신**.

## Scope

- seven representative visual states;
- Korean-first editorial copy;
- original repository-local SVG assets;
- minimal deterministic state switching for visual review;
- `Argument Thread / 논점 연결` signature motion;
- deliberate desktop, tablet and mobile compositions;
- explicit synthetic, provenance, freshness, confidence and limitation labels.

## Run

```bash
python3 -m http.server 4181 --directory reference/business-21-founder-strategy-letter-v1
```

Then open:

```text
http://127.0.0.1:4181/?state=weekly
```

States: `weekly`, `situation`, `evidence`, `tensions`, `options`, `decision`, `mobile`.

## Non-implementation

No email, Drive, Slack or CRM connector; no document ingestion; no enterprise search; no live news or market feed; no financial forecast; no investment or management advice; no authentication; no persistence; no scheduling; no collaboration; no approval workflow; no real AI/model call; no accepted UX; and no backend are implemented.

All companies, people, customers, amounts, source records, statements and recommendations shown in this reference are synthetic.
