# Council UI ↔ global design integration — staged contract (#6065)

- Status: proposed staged contract. It authorises no code by itself. Stage **S0** is implemented in
  the pull request that carries this document; **S1…S5** are proposals awaiting CENTRAL.
- Owner: Web CTO (CENTRAL). Author: LOCAL 1.
- Measured against: `origin/main` `658e1071f80e96be796a8397696daf7722196530`, on 2026-10-28.
- Machine-checked by: `apps/padiem-council-apps/tests/test_6065_mobile_header_contract.py`, run in
  `.github/workflows/padiem-council-apps-ci.yml`. Every later stage must add its own pinned test in
  the same directory before it may claim a surface is integrated.
- Related authorities, unchanged by this document:
  `PADIEM_APPS_PLATFORM_INTEGRATION_CONTRACT_20261027.md` (app ↔ platform: session, AI execution,
  storage), issue **#6046** with PRs #6052/#6053 (country on the request and on the stored file),
  and issue **#5967** (the design prototype itself).

## 1. Baseline: what is live, and how far the proof reaches

The page is not served by `apps/padiem-council-apps/app/`. It is staged into the Chat Worker
bundle by `apps/padiem-chat/scripts/build_b66_worker_dependencies.py` (`APP_ENTRY_BUNDLES`,
`stage_app_entries()`) and served as Workers Assets from `apps/padiem-chat/wrangler.toml`.

| served path | live sha256 (first 16) | bytes | `origin/main` | equal |
| --- | --- | --- | --- | --- |
| `/apps/council/` | `9026d1cd7e958433` | 5366 | same | yes |
| `/apps/council/static/council-app.css` | `bb56ff5e630b44e6` | 14084 | same | yes |
| `/apps/council/static/council-app.js` | `cabb44af11541c4e` | 70711 | same | yes |

All three returned HTTP 200 with no auth wall. The table was taken twice: first at `main`
`658e1071f`, then re-proved at `main` `99e147ea3`, by which time **#6075** (`6630f9e82`) had changed
`council-app.css` and nothing since had touched these three files — both times live equalled main,
and the bytes above are the second pass. The serving version at the first pass was
`7b359e3a-be24-4593-8f66-6edff716573d` (created 2026-10-28T09:50:05Z).

UNPROVEN, and not to be restated as fact: the git SHA behind any serving version (`Source: Unknown`,
no tag or message is attached by Cloudflare), whether any non-council asset also equals `main`, and
that a deploy travelled the authorised Actions path. Consequence for this contract: **a local
measurement of the three files on `main` is a measurement of production today**, and nothing more.

**That last sentence went stale on 2026-10-29 and is corrected here.** After S1 merged, production
still served the pre-S1 `index.html` and `council-app.css` (`9026d1cd…`/`43793ed8…` live against
`cfc3c7ac…`/`d6d22ca6…` in `main`; only `council-app.js` matched). The equality held at the two
passes above because nobody had redeployed in between. Rule for later stages: re-run the three-way
sha256 comparison at the start of every stage, and when it differs, say *deploy drift* — not
*measurement of production*.

## 2. Constraints a visual integration may not break

Each of these is a literal-string assertion that already fails CI if violated. They are the reason
"copy the prototype in" is not a plan.

| # | constraint | pinned by |
| --- | --- | --- |
| 1 | the static directory holds exactly `index.html`, `council-app.js`, `council-app.css` | `tests/test_app_structure.py:73-81` and the builder's `required:` tuple |
| 2 | `council-app.css` contains no `@import` and no `url(` | `tests/test_app_structure.py:118-123` |
| 3 | the token aliases survive verbatim: `--council-bg: var(--page-bg, var(--bg))`, `--council-accent: var(--accent)`; no colour literal | `tests/test_entry_session_and_selection.py:153-163` |
| 4 | these selector strings stay present: `.council-card-select`, `.council-form input,`, `.council-generate,`, `.council-badge-action`, `.council-google`; ≥6 `min-height: 44px`; `:focus-visible`; breakpoints `900px`/`390px`/`1200px` | `tests/test_entry_session_and_selection.py:127-150` |
| 5 | `grid-column: 1 / -1` within 400 characters of `.council-card.active` | same, `:149-150` |
| 6 | Korean card titles and `noindex` stay in the HTML; `data.authenticated === true` and the word `fail-closed` stay in the JS | `tests/test_app_structure.py:106-116` |
| 7 | the endpoint set is closed — no new `/api/*` may appear | `tests/test_module_harness.py:156`, `tests/test_app_structure.py:73-81` |
| 8 | `/padiem-themes.css` is the theme authority shared by Chat, the councillor wrapper and this app, and is not edited from here | `apps/padiem-chat/tests/test_padiem_themes.py` and three further theme tests |
| 9 | CSP `default-src 'self'`, `img-src 'self' data: blob:`, `font-src 'self' data: …` | `apps/padiem-chat/app/worker_config.py:110-121` |

Constraint 2 is the one people trip over: **photography cannot be a CSS background in this app**,
and a font cannot be self-hosted from here. Any image must be an `<img>` built in markup or by
`council-app.js`, and type must keep coming from the shared theme sheet.

## 3. Surface map

Production numbers are from a real Chromium run against the three live files, 2 auth states ×
4 widths (320/390/768/1440) × 3 views = 24 cells, plus a 4-view sweep. Design references are
`reference/padiem-parliament-ai-design-v1/`.

| surface | production today | design counterpart | gap and reuse decision |
| --- | --- | --- | --- |
| Home shell | `static/index.html:24,44-45`; `council-app.css:28-46,110-115` | `.pa-home`, `.pa-hero` (`index.html:138-182`) | production has no hero at all: an `<h1>` then three cards. The hero is the design's largest single addition and depends on photography, so it belongs to S5, not to a header pass |
| Header / nav | `index.html:26-43` (brand, badge, `<select>` language, login button); CSS `:48-109`; static markup, only the badge text is written by JS (`council-app.js:1276`) | `.pa-topbar` + `.pa-nav` (`index.html:82-134`) | same five roles, different vocabulary. The design adds nav items that have no production screen yet (`활용 사례`, `가이드`, `공지사항`) — they must not be ported as dead controls. Reuse the design's row-reflow behaviour, which S0 already reproduced in production terms |
| Tool entry | `index.html:69-91`, CSS `:154-201`, bound by `council-app.js:1372-1387` | `.pa-work-list` / `.pa-work` (`index.html:199-247`), CSS `:1101-1219` | the design card has icon, badge, index number, title, description, select button; production has title, description, select button. The extra parts are DOM the JS must build (`el()` factory `council-app.js:163`) — class names may change only in addition, never by renaming `.council-*` |
| Auth | `index.html:46-68`, CSS `:117-152`, JS `showAuthPanel:1283`, `loginWithPassword:1392`, `bindAuthForm:1451` | **absent** — the prototype has no login surface | nothing to reuse. S4 authors it in the design's vocabulary while keeping `POST /api/auth/password/login`, `GET /api/auth/status` and the Google `return_to=/apps/council/` allowlist untouched |
| Editors ×3 | no markup; hosts `index.html:75,82,89`; DOM built by `speechModule:290-483`, `snsModule:525-936`, `meetingModule:968-1240`; shared CSS `:202-283` | `.pa-editor`, `.pa-meta`, `.pa-paper`, `.pa-document` (`index.html:255+`) | the two structures are close (field group + document surface). Re-map class-level styling only; the prompt assembly (`:78-96`) and payload (`:83`) must keep producing today's byte-identical `kr` request |
| Document list | no markup; `.council-archive` CSS `:284-299`, `.council-saved-list` `:300-323`; built at `council-app.js:402-449,1024-1027,1099` | **absent** (the rail items `templates`/`box` are `aria-disabled` placeholders) | nothing to reuse. The 13×13 px record checkbox this surface measured with was raised to 24×24 px by **#6075**, which also pinned "state the 44px floor in exactly one block". What remains for S2 is the list's own anatomy, not its hit areas |
| Country / style axis | one `<select>` writing `padiem-council-country` (`council-app.js:46,1242-1247`); `index.html:2` `data-theme="light"` is inert (no `[data-theme]` rule exists) | `html[data-country]` × `html[data-style]`, key `padiem-parliament-theme` (`parliament-app.js:11-13,233-254`) | the design's two axes are the whole point of "4개국 × 5스타일". Importing them means a third storage key and a real decision about whether the 5 styles are user-facing. §6 |

## 4. Stages

Every stage is its own pull request, its own exact-head CI run and its own preview deployment.
No stage in this list deploys to production; production release stays with CENTRAL.

- **S0 — mobile header reflow (this PR).** The baseline for these numbers is `main` *after* #6075
  landed, so nothing below is credited twice. Measured before: 320px
  `scrollWidth − clientWidth = 30` with the actions group ending at x=350.1 and the login button
  hanging off the viewport; the status badge 34×114 px ("로그인 필요" standing on six lines,
  47.4×72.4 = three lines at 390); the brand name 71.3×51.2 px on two lines; the "콘텐츠 언어"
  label 130×95.9 px stacked vertically; the login button 42×64.4 px reading "로그/인".
  After: overflow 0 and no occlusion in all 24 cells; every header item is one line at every width
  — brand 118.2×25.6, badge 85.5×30.8, language label 177.6×44, login 65.9×44. Header height
  153 px at 320 and 101 px at 390 (signed-in 320: 116.9 → 101), unchanged 65/69 px at 768/1440.
  #6075 already raised the `<select>` to the 44 px floor and the 활동집 record checkbox to 24×24;
  this stage only deleted the stale `min-height: 32px` that the base rule still carried, so the
  floor is stated once (rendered height unchanged, measured).
  Files: `static/council-app.css`, `tests/test_6065_mobile_header_contract.py`,
  `docs/6065/mobile-header-before-after.png`, `README.md`.
- **S1 — header skin, no new controls (implemented in this PR).** Adopted: the design's fluid
  gutter and gap (`12px clamp(20px,4.85vw,70px)` / `clamp(8px,1.2vw,18px)`), its 30×30 stroke brand
  mark drawn in `currentColor` (inline SVG, so no asset and no `url()`), its brand type scale
  (16.5px/700/-0.01em/1.2), and its open-tool marker — a 2px accent outline with 2px offset,
  replacing the inset 3px bar nobody could see. `council-app.js` is byte-identical, so the prompt,
  payload, save and auth paths are untouched by construction.
  Deliberately **not** adopted: the design's `position: absolute` transparent bar. It is readable
  only because it sits on a photograph, and S1 adds none — production keeps its surface fill and
  hairline. The country/style axis is also not introduced, per CENTRAL's decision that the five
  styles stay internal; `test_the_five_styles_stay_internal` now fails if `data-style` or the
  design's theme key ever appears in this app.
  Measured: 32 cells (2 auth states × 4 widths × 4 views) overflow 0, occlusion 0; the active-card
  ring stays inside the viewport (320: card 14..306, ring 10..310). At ≤767 the mark's left edge
  (14px) equals the content column's (14px); at 1440 the header keeps the design's full-bleed
  gutter (mark 69.8) while the content stays a centred 920px column (title 260) — the design has
  the same relationship (mark 69.8, cards 271.9).
  Accepted limitation, corrected here: the design renders Pretendard because it self-hosts it
  (canvas differential 118.1px against a 127.7px fallback); this app has no `@font-face`, so the
  same string renders at 127.7px. S1 matches the type *scale*, not the *face*. §6-1 covers the
  font decision.
- **S2 — tool entry card anatomy + document list floor (implemented in this PR).** Adopted from
  `.pa-work`: a 30×30 icon slot holding a 26×26 stroke SVG, the 22×2 rule under it, a two-column
  card (`30px minmax(0,1fr)`) with the editor spanning `1 / -1`, and the design's fluid title
  `clamp(17px, 1.39vw, 20px)` / `-0.02em` (measured 17px at ≤768, 20px at 1440 — the design's own
  two values). The archive checkbox keeps #6075's 24×24 box and is now wrapped in
  `label.council-archive-check`, measured 44×44 at all four widths; pressing 5px inside the label's
  left edge toggled the box in every width, and the book path still reads
  `.council-book-check:checked`. The skip link's focused box went 25.6 → 44px tall.
  Found and fixed while reviewing the capture: taking 42px away from the text column made the
  Korean description break inside a word at 390; both card strings now carry
  `word-break: keep-all`.
  Flow proof: five cases (speech/sns/meeting at kr, speech at fr, meeting at us) run identically on
  `main` and on this branch — same `/api/chat` and `/api/projects/p1/files` bodies, same rendered
  result, same dialog count. kr sends no `country` field, fr/us send it on both requests, and the
  SNS composition still posts as `application/json`.
- **S3 — editor pass for the three tools (implemented in this PR).** CSS only, one file; the DOM the
  three modules build is untouched, so prompt assembly, payload, save and permission paths are
  unchanged by construction and were re-proven by the same five-case A/B as S2.
  Adopted from the design: `.pa-meta` (a 14px-radius panel with `clamp(14px,1.8vw,20px)` padding),
  the 12px/.04em muted label register, fields at `10px 12px` / 15px / 14px radius on the 44px floor,
  `min-height: 92px` resizable textareas, the filled pill primary action (`.pa-draft`: 999px radius,
  weight 700) and hairline pill secondaries (`.pa-back`), and `.pa-paper` as the result surface — a
  padded panel whose textarea is a borderless sheet at 16.5px/1.85 with `min-height:
  clamp(320px, 54svh, 620px)`, focus carried by the panel border instead of a second ring.
  The design's two-column editor (`minmax(0,320px)` + paper) is adopted at ≥900 as `340px` + 1fr,
  gated on `:has()` so a tool with no result yet keeps one column instead of showing an empty
  right side; where `:has()` is unsupported the rule is ignored and today's single column remains.
  Measured: 1440 columns `340px 532px`, form 340, result and lists at x=631; 768/390/320 single
  column (form 706/332/262); 32 cells overflow 0, occlusion 0.
- **S4 — auth surface authored in the design's vocabulary.** Acceptance: fail-closed gate intact,
  the Google return allowlist intact, and no new endpoint.
- **S5 — hero, photography, and localised chrome.** Blocked on §6.

## 5. Non-goals

No new AI engine, router, store, index or RAG path. No new endpoint or permission model. No second
theme authority. No forced approver step for any user. No cross-country 1:1 title mapping, and no
claim that choosing a country makes a document legally correct — country is output language and
expression only, exactly as #6046 defines it. A prototype click that only moves a class is not an
E2E result: the design's own `paStatus` announcements are simulated, and no stage may cite them as
proof that generation or saving works.

## 6. Decisions this contract cannot make for CENTRAL

1. **Asset budget.** The prototype ships 7 photographs (2,647,683 bytes) and `assets/fonts/`
   (1,997,707 bytes including licence texts). Staged into the Chat Worker bundle, that is added to
   every cold load of `/apps/council/`. Which images, at what size, is an owner call.
2. **`url()` policy.** Constraint 2 currently makes CSS-referenced imagery impossible here. Either
   photography stays `<img>`-only, or the ban is consciously narrowed to `@import` plus remote URLs.
3. **Are the 5 styles user-facing in production?** If yes, where the choice persists: a third
   `localStorage` key beside `padiem-council-country` and `padiem-council-tool`.
4. **Localised chrome.** The app has no UI dictionary — the header, cards and login strings are
   hard-coded Korean (`index.html`, `council-app.js:296-310,531-537,974-979`). The prototype's
   `COPY` dictionary covers screen strings for `us`/`uk`/`fr` only. Translating the app's chrome is a
   content decision, and PR #5660 is already building locale packs for Chat's own surface.
5. **Ownership boundary found while writing S0.** #6075 landed in the same file mid-stage and owns
   the 44 px floor statement (`tests/test_6046_mobile_touch_floor.py` pins that it appears once and
   never inside a media query). S0 therefore adds no floor declaration of its own; it only removes
   the base rule's stale `min-height: 32px`. Any later stage that needs a different control height
   must extend that one block rather than restate it.

## 7. Evidence index

- Harness: `council6065_harness.py` (local, read-only; `/api/chat` answered from a canned string,
  so no model call leaves the machine).
- Measurement: `council6065_measure.py` → `live_measure.json`, 2 states × 4 widths × 4 views, with
  the before run preserved alongside the after run.
- Occlusion pass: 24 cells × 14 controls, `elementFromPoint` at each control's centre — 0 occluded,
  0 off-viewport, 0 horizontal overflow.
- Mutation check of the four new guards: 6 mutations, each detected by exactly one test.
