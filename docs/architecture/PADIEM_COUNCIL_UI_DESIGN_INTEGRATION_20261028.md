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

### 1.1 S5: which commit production is serving, positively identified

`tools/council_s5_live_verify.py` now attributes the served bytes instead of only reporting drift: it
takes the git blob id of each served asset (after removing Cloudflare's injected analytics tag from
the HTML) and returns the newest commit on `main` whose three blobs equal all three served blobs.
Measured 2026-10-29 with `main` at `b884ab7b9`:

```
SERVING=71a74dee29ea119b98b08a1391c579b9bf76651b
        (2026-10-28 21:00:12 +0900, fix(5573) … (#6082)) — main is 26 commits ahead of it
MERGED_BUT_NOT_SERVED:
    81813dbc8 feat(council): style auth and archive surfaces S4 (#6103)
    d849c4a18 feat(council): integrate three editor visual skins S3 (#6095)
    d941fb33a feat(council): integrate design cards and archive touch targets S2 (#6088)
    17b9cc65f feat(council): apply global design header skin S1 (#6083)
```

That commit is the last `B62 Production Code Deploy Gate` dispatch (`run 40684361588`,
2026-10-28T12:00:43Z, success), so the deploy history and the served bytes agree. S0 (`14ab16d81`)
is an ancestor of `71a74dee2`; S1 is not. **The live design state is exactly S0, and #6065 S1–S4 are
merged but not served.**

Still not claimed: that blob attribution proves *who* deployed. It identifies which code is live from
its bytes; Cloudflare's own version metadata attaches no source SHA (`Source: Unknown`), so the
deployment path is read from the Actions run, not inferred from the content. And the rule for the
HTML hash is now fixed: the served `index.html` carries one extra Cloudflare Web Analytics
`<script>` — measured 366 bytes on its own line, so 367 including that newline — and removing
exactly that makes the served HTML **byte-identical** to the `index.html` committed at
`0027fc413` (#6052, the last commit to touch that file before S1), git blob `daeb754fbc7f`. That
exactness is what makes the attribution above trustworthy rather than approximate.

### 1.2 S5 post-deploy readback — the design is live

The release owner (not this lane) deployed current main while this contract was being written:

| fact | value |
| --- | --- |
| deployed SHA | `9430f39931616542a298dfe0d15a5a2c84813845` (#6112) — council assets identical to S4 `81813dbc8` |
| workflow run | `B62 Production Code Deploy Gate` run `40786832140`, success, 2026-10-28T23:21:54Z |
| cloud version | `DEPLOYED_VERSION_ID=302b33f6-0c28-4b22-a16a-f2d1c7acdea8` |
| refused first dispatch | run `40786525919` failed on `Require explicit production code deploy authorization` with `CONFIRMATION:` empty; the rollback step logged `No recorded previous version; manual rollback required` and **nothing was republished** — production stayed on `9a561b5e-e4f0-46b9-9a7d-f4479c038ba5` until the authorised run |
| D1 in this release | `D1_SCHEMA_QUERY=READ_ONLY`, `D1_IDENTIFIER_OUTPUT=0`; the last sanctioned plan (`B62 general D1 migration gate (Chat)`, run `40679268473`) recorded `B62_D1_PLAN_APPLY=0`, so no migration travelled with the deploy |

Re-running the tool after that deploy: all three assets `MATCH`, `SERVING=9430f3993`,
`main is 0 commits ahead`, and every stage marker is present on production —
`S1mark=True/30`, `S1name=16.5px/-0.165px`, `S2cols=30px <auto>` with `icon=30`, `S3field=14px`,
`S4auth=14px`, `S0wrap` at 320/390/768 and `nowrap` at 1440, `countries=kr,us,uk,fr`, sign-in panel
rendered signed-out at all four widths, and overflow 0 / out-of-viewport 0 / sub-44px 0 at every one of
the four widths. → `DEPLOYED_TO_MAIN_BYTES=YES S1_S4_MARKERS=YES GEOMETRY_CLEAN=YES`,
**`LIVE_VERIFIED=YES` for the unauthenticated surface.**

Visual proof, not only numbers: `docs/6065/s5-live-home-1440.png`, `s5-live-home-390.png`,
`s5-live-tooltap-1440.png`, `s5-live-tooltap-390.png` — the production screen renders the stroke brand
mark, the card icon column with its 22×2 rule, the pill actions and the panel surfaces, Korean wraps at
word boundaries at 390, and tapping a tool while signed out still leaves **exactly one** `.council-form`
(the login form) at all four widths, i.e. the fail-closed gate holds in production.

Not yet verified, and not claimed: the **authenticated** pass over the three editors at the four
widths, live KR/US/UK/FR generation, save-and-reentry, SNS media order, the activity book, copy/TXT and
keyboard focus (S5 steps 3–4). Those need an authorised test account, consent for paid model calls and
real file writes; they are a separate bounded run, and step 5's "the existing user documents survived"
is currently supported only by *no storage write happened* plus the gate's pre-deploy
`project_files=14` count — a re-measure needs the same authorised read.

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
- **S4 — auth surface authored in the design's vocabulary (implemented in this PR).** The prototype
  has neither a sign-in panel nor a record list, so nothing could be ported; both surfaces were
  built from the design's *existing* vocabulary instead of invented styling — the field-panel radius
  and padding (`.pa-meta`), hairline row separation (`.pa-strip li + li`) and the hairline pill
  (`.pa-back`). CSS only; the markup and the module JS are not in the diff.
  Measured: the saved list and the meeting archive had **no surface at all** (radius 0, no border,
  no padding — a bare `<ul>` of grey chips); they are now panels (14px radius, `clamp(14px,1.8vw,20px)`
  padding, hairline border) whose rows are bare 600-weight lines separated by a 1px hairline
  (row 1 border-top 0px, row 2 1px). The sign-in panel moved 16 → 14px radius with the field-panel
  padding, its heading took the card-title scale (20px at 1440), and the Google link became a
  999px pill at 45.6px tall.
  Preserved and re-proven: signed out, exactly one `.council-form` exists (the login form) and no
  tool builder attaches; submitting credentials reaches only `POST /api/auth/password/login`, and
  without a confirmed session the panel stays open with the failure status and zero builders; the
  Google link keeps `return_to=%2Fapps%2Fcouncil%2F`. Six A/B cases (three tools at kr, speech at
  fr, meeting at us, plus the signed-out login attempt) produced identical request bodies and
  identical rendered output on `main` and on this branch.
  Two corrections recorded here rather than hidden: an initial batch of body-anchored CSS
  replacements hit the wrong rule because the archive and saved rows share an identical body — the
  file was reverted and every rule rewritten by its own selector, then re-verified through computed
  style; and a `border-radius: 999px` on the reference chip was deleted because the shared 44px
  floor block declares 10px later and always won.
- **S5 — release the integrated design and verify it live (this PR ships the verification, not the
  release).** CENTRAL's order for S5 is: confirm main and the active release owner → protected
  deploy of main by the release owner → three-asset readback + authenticated/unauthenticated browser
  at 320/390/768/1440 → live KR/US/UK/FR generation, country filtering, saved-document re-entry, SNS
  media order, activity book, copy/TXT, touch and keyboard focus → confirm the existing user files
  survived and the test artifacts are gone. LOCAL 1 owns the readback, the browser evidence and the
  post-deploy regression; the deploy itself is LOCAL0/CENTRAL's, so **this PR touches no runtime
  code** — `tools/council_s5_live_verify.py` is read-only (it never signs in, generates or stores)
  and the tests pin the rules that keep the readback from lying.
  Rules S5 had to discover, each now guarded (§1.1 for the beacon, and
  `tests/test_6065_s5_readback_rules.py`):
  1. an empty response must never read as a match — two empty bodies hash equal, so the verdict
     ladder checks non-empty before it compares anything;
  2. the served HTML is not the source HTML — Cloudflare injects one analytics tag, normalised out
     by a pattern that takes the tag **plus the newline it arrives on** and never the source's
     newline before it (a leading `\s*` put a byte-perfect deploy one byte short of MATCH forever);
  3. drift must be *attributed*, not just reported — hence `SERVING=<sha>`;
  4. the skip link is parked at `left:-9999px` until focused, so counting it as an overflow offender
     or a 44px target fails a clean page forever;
  5. the marker harness must wait on `#councilAuthPanel` losing its `hidden` attribute, not on a
     fixed sleep — the panel unhides only after `/api/auth/status` resolves, and a 700 ms sleep
     reported a hidden sign-in panel at 390 on a page that was fine.
  Baseline measured 2026-10-29 (`main` = `b884ab7b9`, tool run exit 1 by design): three assets
  `DRIFT`, `SERVING=71a74dee2`, S0 live and S1–S4 merged-not-served, and the live page geometry
  already clean — overflow 0, offenders 0, sub-44px targets 0 at 320/390/768/1440,
  `countries=kr,us,uk,fr`, sign-in panel visible in the signed-out state at all four widths.
  **`LIVE_VERIFIED=NO` at that moment** — and the release owner deployed current main shortly after,
  so §1.2 carries the post-deploy read (`LIVE_VERIFIED=YES` on the unauthenticated surface, with the
  authenticated steps 3–4 still open). The tool is the re-check: it exits 1 unless
  `DEPLOYED_TO_MAIN_BYTES`, `S1_S4_MARKERS` and `GEOMETRY_CLEAN` are all YES.
  Guard strength, measured by mutation (each mutation applied alone, then reverted and byte-checked
  against the snapshot): beacon eats the source newline → 1 test red; beacon leaves its own newline →
  2 red; empty-response branch removed → 1 red; skip-link exclusion removed → 1 red; settle-wait
  removed → 1 red; settle sleep lengthened past 500 ms → 1 red. Two are honestly disclosed as **not**
  load-bearing: dropping the `length_equal` conjunct from MATCH stays green (a full SHA-256 compare
  already implies it — kept as a second, independent statement of the empty-response rule the release
  owner asked for), and the skip-link `continue` in the *overflow* loop changes nothing on today's DOM
  because the inline `!parked(el)` predicate already excludes a left-parked element; the same guard
  in the *touch* loop is load-bearing on the real page (sub-44 count 1 → 0 at all widths).
- **Deferred behind §6 — hero, photography, localised chrome.** Not part of #6065 S5; the CTO's
  S5 order explicitly bans new visual features, photos or fonts without a discrete issue.

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
- S5 readback: `tools/council_s5_live_verify.py` (read-only) → `s5_live_verification.json` in the
  system temp dir, holding the three-asset table with `cf_injected_bytes` and the per-width marker
  set. Re-run it after the release-owner deploy; the exit code is 1 while any of
  `DEPLOYED_TO_MAIN_BYTES` / `S1_S4_MARKERS` / `GEOMETRY_CLEAN` is NO.
- S5 deploy provenance: last `B62 Production Code Deploy Gate` dispatch `run 40684361588`
  (2026-10-28T12:00:43Z, success, head `71a74dee2`) — the Actions record, independent of the
  byte attribution in §1.1.
