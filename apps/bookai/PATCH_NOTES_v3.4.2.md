# StoryMemory v3.4.2 — SM-088 Gold / Blind Harness Evaluation

- Upgrades Universal Source runtime to 1.3.0.
- Fixes truncated lexical passage indexing and visible-boundary candidate fallback.
- Adds lazy prior-unit lookback for Book recall without a mandatory knowledge DB.
- Adds optional AI Retrieval Planner/query-hint hook for aliases/transliterations.
- Gold Books 1–20: entity exact 92.31%, relationship exact 95%, same-section 100%/100%, cross-unit first-mention recall 90%, spoiler leakage 0%.
- Planner variant closes the `헬렌` → `헬레네` lexical gap at exact Gold rank 1.
- Blind Books 21–24 with zero knowledge rows: rare locator 100%, section retrieval 100%, cross-unit recall 100%, spoiler leakage 0%, Grounded route 100%.
- Static content bytes unchanged from v3.4.1.
- No Neon write, Cloudflare, Portal, DNS, or Book21+ knowledge mutation.
- Deployment remains deferred to BI Portal `/b61/`.
