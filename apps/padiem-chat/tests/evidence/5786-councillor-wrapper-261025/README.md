# #5786 councillor blog wrapper — browser evidence

Captured 2026-10-25 in Chromium (Playwright). Files prefixed `00-before`,
`p3-before` came from the **live site**; `p3-after` and the numbered files come
from a locally served build of the branch
(`PADIEM_CHAT_RUNTIME_MODE=mock`, `uvicorn --port 8099`).

## Pass 3 — readability, tap targets and spacing (`p3-*`)

Measured on the live page, not eyeballed. `contrast_before_light.json` and
`contrast_after_light.json` carry every number.

| text | size | before | after | WCAG AA |
| --- | --- | --- | --- | --- |
| fact label / source / footer line | 12px | 4.37–4.64 | 6.1–6.5 | pass |
| activity date (gold) | 13px | **2.75** | 5.33 | was failing |
| hero name (over video, sampled from pixels) | 116px | — | 11.0 | pass |
| hero lead | 20px | — | 14.5 | pass |
| primary CTA label on accent | 15px | — | 5.3 | pass |

| control | before | after |
| --- | --- | --- |
| topbar theme / motion / login | 33px tall | **44px** at 390/820/1440/1920 |
| CTA / channel chip | 52 / 48px | unchanged |
| section left edge | 130px | 130px at every width (verified, not changed) |

`p3-before-activity-1440.png` vs `p3-after-activity-1440.png` is the stable
comparison — the same scroll position with no video in frame. The `p3-*-1920`
pair also differs by the playing video frame, so use the activity crops for the
readability judgement.

## Desktop face crop (pass 2, `00-before` / numbered)

| file | box | aspect | source height cropped |
| --- | --- | --- | --- |
| `00-before-1920-production.png` | 1920×940 | 2.043 | 93px of 720 (47px off the top) |
| `01-light-1920.png` | 1920×1080 | 1.778 | 0px |
| `02-light-1440.png` | 1440×810 | 1.778 | 0px |

The source is 16:9, so any wider box forced `object-fit: cover` to eat the
frame. Pinning the hero to `min(100svh, 56.25vw)` at ≥1000px makes the box and
the source the same shape, and nothing is cropped. Below 1000px the mobile
composition the owner approved is untouched (`03-light-820`, `04-light-390`).
`before_measure.json`, `after-light_measure.json` and `after-dark_measure.json`
carry the numbers per viewport.

## Theme

| file | what it shows |
| --- | --- |
| `01`–`04` | default Light at 1920 / 1440 / 820 / 390 |
| `05`, `06` | the same page in Dark (topbar toggle) |
| `07-light-profile.png` | light body: white canvas, hairline rules, SUIT/SUITE type |
| `08-light-media-band.png` | the one dark band the owner allowed, with the 2025 interview labelled as 2025 footage |

Toggling does not reload: scroll position and the playing hero video survive the
switch, and the choice lives in `?theme=` rather than browser storage.

## Unchanged contracts

`e2e_result.json` / `e2e_v2_result.json` are the earlier S4 and #5803 runs, kept
because they record the util-screen deep link (`#padiem-util/*` opening the
existing PADIEM screens) and the guest/signed-in boundary that this pass did not
change.

No credential, cookie or private project data appears in these files. Hero and
interview media are the councillor's office-supplied files served from
`media.padiem.net`; they are referenced by URL and are not committed here.
