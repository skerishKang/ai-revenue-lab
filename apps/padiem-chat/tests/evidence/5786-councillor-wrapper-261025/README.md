# #5786 councillor blog wrapper — browser evidence

Captured 2026-10-25 in Chromium (Playwright). `before-*` came from the live
site at the #5803 build; `after-*` / numbered files come from a locally served
build of this branch (`PADIEM_CHAT_RUNTIME_MODE=mock`, `uvicorn --port 8099`).

## Desktop face crop (the reason for this pass)

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
