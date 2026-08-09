# B2 V2 validation limits

The implementation branch was produced through the connected GitHub API rather than a local checkout.

Completed:
- branch isolated from current `main`;
- scope restricted to `apps/living-travel/**`;
- no external runtime assets introduced;
- canonical and demo routes use local CSS only;
- legacy QA/test markers retained visually hidden where required;
- no backend/auth/db/provider/deployment workflow files changed.

Still required before merge:
- repository CI / pytest;
- real Chromium desktop/tablet/mobile capture;
- horizontal-overflow check;
- keyboard focus and reduced-motion check;
- owner visual review on the deployed live surface.
