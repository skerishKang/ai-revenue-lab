# #5786 councillor blog wrapper — browser evidence

Captured 2026-10-25 against a locally served Chat instance
(`PADIEM_CHAT_RUNTIME_MODE=mock`, `uvicorn app.main:app --port 8099`) in
Chromium through Playwright, desktop 1440x900 and mobile 390x844.

| file | what it shows |
| --- | --- |
| `evidence-5786-hero-desktop.png` | public cinematic hero: placeholder film layer, `시제품` badge and the disclosure line that keeps the temporary material from reading as the councillor's own |
| `evidence-5786-hero-mobile-390.png` | same hero at 390px: single column, no horizontal scroll, disclosure below the actions row |
| `evidence-5786-util-sns-deeplink.png` | `#padiem-util/sns` opening the **existing** util screen (SNS 홍보 tab, blog/facebook/instagram tabs, photo field) with its own `util-menu.css` styling |
| `e2e_result.json` | every measured key from the run |

The session state is stubbed only for `GET /api/auth/status`, to exercise both
branches of the admin gate; no credential, cookie or private project data is
present in these files.
