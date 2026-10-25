# #5786 councillor blog wrapper — browser evidence

Captured 2026-10-25 against a locally served Chat instance built from `main`
(`PADIEM_CHAT_RUNTIME_MODE=mock`, `uvicorn app.main:app --port 8099`) in
Chromium through Playwright.

| file | what it shows |
| --- | --- |
| `01-hero-1920.png` | public hero with the R2 background video playing, at 1920 |
| `02-hero-1440.png` | same hero at 1440: name, current office, two CTAs and the fact strip all inside the first screen |
| `03-hero-820.png` | tablet |
| `04-hero-390.png` | mobile: single column, no horizontal scroll |
| `05-media-section-1440.png` | 2025 introduction interview (labelled as 2025 footage) plus the official-record link list |
| `06-profile-activity-1440.png` | profile from the assembly registry and the activity timeline |
| `07-signedin-footer-admin.png` | the management path in the footer, only after an authenticated status read |
| `08-padiem-util-sns-unchanged.png` | `#padiem-util/sns` opening the **existing** util screen, unmodified |
| `e2e_result.json` | measured keys from the S4 run |
| `e2e_v2_result.json` | measured keys from the redesign run (video paint/play, four viewports, admin path) |

Session state is stubbed only for `GET /api/auth/status`, to exercise both
branches of the management gate. No credential, cookie or private project data
appears in these files. The hero and interview media are the councillor's
office-supplied files served from `media.padiem.net`; they are referenced by
URL and are **not** committed here.
