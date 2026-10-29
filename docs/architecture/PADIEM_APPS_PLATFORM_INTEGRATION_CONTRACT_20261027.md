# PADIEM Apps ↔ Platform Integration Contract

- Status: Active contract for independently entered PADIEM apps. Implementation-neutral: it
  describes what the platform already serves and what an app may depend on.
- Owner: Web CTO (CENTRAL). Author: LOCAL 0 (common integration layer).
- Follows up on: [#5927](https://github.com/skerishKang/ai-revenue-lab/issues/5927). The council
  app itself is on `main` as of `544e8d163` (PR #5929); the items it recorded as not yet connected
  are the ones this contract fixes or names.
- Entry decision (CENTRAL, 2026-10-27): the first 의원3종 release is served from a
  **same-origin path on `chat.padiem.net`** — `#5937` ships it at `/apps/council/` after the
  collision check came back empty. It reuses the existing host-only session, Origin rule, B14 lane
  and file store. No auth bridge for another host, no relaxation of the cookie `Domain`, no second
  session and no forwarded API `Origin` is to be implemented.
- Machine-checked by: `.github/scripts/padiem_apps_integration_contract.py` and
  `.github/tests/test_padiem_apps_integration_contract.py`, run in
  `.github/workflows/padiem-apps-integration-contract-ci.yml`.
- Supersedes for this purpose: `PORTAL_PRODUCT_INTEGRATION_CONTRACT.md`, which is a pre-#83
  draft that still describes `apps/portal/` (no longer present) and Firebase identity. That
  document is not the app↔platform authority; this one is for apps reusing the live PADIEM
  platform. It does not change `PADIEM_PRODUCT_ACCESS_PROJECTION_4546_20261013.md`, which stays
  the authority for the product-availability projection.

## 1. What this is, and what it is not

A PADIEM **app** is an independently entered product surface: its own screens and work logic,
reaching the platform's existing authentication, AI execution and storage. The first is the
의원3종 entry (축사·인사말 / SNS 홍보 / 회의정리·활동집).

This contract creates **no** new engine, model router, identity scheme, database, bucket or
Business number. Every capability below already exists and is cited. Where a capability does not
exist yet, §5 says so plainly instead of approximating it with a new mechanism.

## 2. Reuse map (measured at the cited revision)

| Need | Existing authority the app reuses | Evidence |
| --- | --- | --- |
| AI execution | `POST /api/chat` on the Chat Worker → model policy → UsageGate → B14 | `apps/padiem-chat/app/chat_routes.py:841,845,1033,1086,1093,1100` |
| Work identity on that lane | `util` field, closed set, refused before any model call | `apps/padiem-chat/app/request_contract.py:36,132-137`, `declared_util_scope` `:115` |
| Calendar-branch separation | declared scope skips the native-calendar branch **including** its second classification | `apps/padiem-chat/app/chat_routes.py:1044-1053`, `native_calendar_intent.py:195-202` |
| Session / user | `padiem_session` + `GET /api/auth/status`, revocation-aware | `auth_routes.py:211-268`, `session_revocation_guard.py:156-215` |
| Model routing authority | B14 (`ai-revenue-korean-ai-platform`), service-bound | `apps/padiem-chat/wrangler.toml:72-75` |
| Storage | `GET|POST /api/projects`, `…/files`, `…/files/{id}`, `…/original` | `app_factory.py:568-575` |
| Owner isolation | every file route passes `_identity`, then `get_project(uid, pid)`; foreign or malformed → non-disclosing 404 | `project_file_routes.py:70-89`, `history.py:1159-1164` |
| Same-origin rule | expected Origin from `Settings.public_base_url` only; GET/HEAD out of scope | `same_origin_guard.py:16-30,42-45,127-144` |

## 3. The platform surface an app may depend on

Exactly these, with these methods — the checker refuses if any is missing, and an app may not
assume anything else:

```text
GET    /api/auth/status
POST   /api/auth/password/login
POST   /api/chat
GET    /api/projects
GET    /api/projects/{project_id}/files
POST   /api/projects/{project_id}/files
GET    /api/projects/{project_id}/files/{file_id}
DELETE /api/projects/{project_id}/files/{file_id}
GET    /api/projects/{project_id}/files/{file_id}/original
```

- **Sign-in inside the app.** `POST /api/auth/password/login` is the same credential route Chat
  uses (`{identifier, password}`, one non-disclosing `401`), added so a signed-out visitor signs in
  inside the app's own page instead of being routed to the Chat home (#5942). It is not a new
  authority: registration, password reset and logout stay Chat's, and the checker refuses if the
  route disappears. A Google round trip returns to the app only through the Worker's signed state
  and one exact allowlist (`app/auth.py` `OAUTH_RETURN_TARGETS`); a caller-supplied URL never aims
  the redirect, and the Chat default stays `/`.

- **Work identifiers.** `speech`, `sns`, `meeting` today. A declaration makes the request skip the
  native-calendar branch; it grants no identity, tier, entitlement or tool scope, and an unknown
  value is refused with `422` before any model call. An app cannot widen the set at runtime.
- **Stored text.** `text/plain`, `text/markdown`, `text/csv`, `application/json` with extension↔
  media-type agreement (`packages/padiem-ai-core/padiem_ai_core/document_normalization.py:100-105`).
- **Stored images.** `image/png`, `image/jpeg`, `image/webp`, validated against the first 12 bytes
  (`apps/padiem-chat/app/project_files.py:18-45`) so a renamed text payload cannot masquerade as
  an original.
- **Existing ceilings.** request body `2359296` bytes (`project_file_routes.py`), and the stored
  row is D1's own per-row limit — `CHECK(length(CAST(content_text AS BLOB)) <= 2097152)`, migration
  `077_project_files_text_byte_bound.sql`, mirrored by `PROJECT_FILE_MAX_TEXT_BYTES`
  (`project_files.py`). These are the platform's numbers, not the app's: #5882 PR-E removed the
  former arbitrary `160000`-byte body / `40000`-character row caps, which refused bodies D1 holds.
- **Re-entry.** the file detail route alone adds `content` to the projection; `public_dict` never
  carries it. A saved draft is distinguished from an absent file by the caller treating a blank
  text as "no saved draft" and a failed roster read as "leave the surface untouched".

## 4. Authentication: what actually works from another origin

This is the part an app most often gets wrong, so it is stated with its evidence.

1. `padiem_session` is `Secure; HttpOnly; SameSite=Lax` with **no `Domain` attribute**
   (`apps/padiem-chat/app/auth.py:21` and `session_cookie_kwargs`). It is therefore host-only:
   a browser will not send it to any other host.
2. `SameOriginGuardMiddleware` compares the request `Origin` **exactly** against
   `Settings.public_base_url` and denies a same-registrable-domain sibling
   ("https://chat.example.com != https://app.example.com", `same_origin_guard.py:16-30`).
   Missing `Origin` on a cookie-authenticated mutation is denied; unset/invalid config is `503`.
3. `GET /api/auth/status` returns `email`, `name`, `picture` only (`history.py:216-217`) — it
   deliberately does **not** disclose the user id. So an app cannot trade this route for an
   internal identity assertion, and no app should ask for one on that route.

Consequence:

| Integration mode | Auth works? | Why |
| --- | --- | --- |
| **Path-mounted on the PADIEM origin** (app assets served by, or routed to, the app's Worker under `chat.padiem.net/…`) | **Yes** | same host ⇒ the host-only cookie arrives; same origin ⇒ mutations satisfy the guard. This is what `static/councillor/` and `apps/padiem-council-apps/` (on `main`) already assume, and it is the entry CENTRAL selected for the first release. |
| **Separate Worker reached through a service binding, with the cookie forwarded** | Only when the app is itself served on the PADIEM origin | the forwarding pattern exists and is proven twice: `apps/ai-reward-router/src/income-pipeline/padiem-session-auth.ts:112-160,246-281` and `reference/business-66-padiem-quote-v1/_worker.js:73,440-447`. Both rely on the browser delivering the cookie to *their* origin first. |
| **A genuinely different hostname** (`council.padiem.net`, `*.workers.dev`) | **No — not with existing authorities, and not authorised for the first release** | the cookie never arrives (§4.1) and a direct browser call is denied by the guard (§4.2). Closing it would need Cloudflare zone routes on the PADIEM host or a reviewed inbound identity lane; CENTRAL has chosen neither for now, so §5 keeps them reserved rather than open. |

`apps/ai-reward-router/DEPLOYMENT.md:91-97,160-166` reached the same conclusion independently:
a `workers.dev` host "cannot receive it", and its remaining prerequisite is routes on
`chat.padiem.net`.

**Two things an app must never do to "fix" this.** Forwarding the caller's `Origin` (or any
`Origin`) to satisfy the guard, and introducing a second session/token scheme. The first empties
the CSRF boundary that exists precisely because `SameSite` is a *site* boundary, not an origin
boundary; the second duplicates two working bridges and creates a second authority. Both are
rejected by §6.

### 4.4 The shipped same-origin entry: `/apps/council/`

The council app keeps its own static directory as the only copy of its files.
`apps/padiem-chat/scripts/build_b66_worker_dependencies.py` (`generate_runtime` →
`stage_app_entries`) assembles `apps/padiem-council-apps/static/` into the generated bundle at
deploy-build time, and the Chat ASGI app grows no route. Nothing app-owned is committed under
`apps/padiem-chat/**`, so the entry cannot drift from the app and a rebuild always refreshes from it.

The staged layout mirrors `apps/padiem-council-apps/app/app_factory.py` (entry at `/`, everything else
under `/static/*`) because that is what makes the entry page's own relative `./static/…` references
resolve:

| Staged into the bundle | Served at |
| --- | --- |
| `static/apps/council/index.html` | `/apps/council/` |
| `static/apps/council/static/council-app.css` | `/apps/council/static/council-app.css` |
| `static/apps/council/static/council-app.js` | `/apps/council/static/council-app.js` |

**The deploy-contract fact this entry turned on.** `base_dir` is applied to `main`, and **not** to
`[assets] directory`, which wrangler resolves against the config file's directory. Measured on the
first attempt (RUN `40433130415`): with `directory = "static"` the packaging step logged
`Read 162 files from the assets directory …/apps/padiem-chat/static` — 158 files + 4 directories —
and the staged entry never reached the Assets set. The generated tree is what the release must
upload, so `[assets] directory` is now `.b66-worker-src/static`. Switching it is loss-free: the
bundle's static tree is `copytree` of the source static plus the entry, and
`test_generated_bundle_is_a_superset_of_the_source_assets` refuses any dropped or altered
pre-existing Chat asset, while `test_assets_are_uploaded_from_the_generated_bundle` refuses the two
paths naming different trees. The Python module bundle cannot substitute: it carries `.html` files
only (measured in the same log), which is why the first attempt served the entry HTML through the
Worker — CSP and `charset=utf-8` on the response, no `CF-Cache-Status` — and answered 404 for the
stylesheet and script.

Two facts the entry inherits from the existing surface, recorded rather than fixed here: static asset
responses come from the Assets binding and therefore do **not** pass through
`response_headers_for_path`, so they carry no `Content-Security-Policy` (measured on `/` and
`/styles.css`, and already true for `static/councillor/`); and the entry HTML itself is public, with
the app gating every tool on `GET /api/auth/status` before it attaches a builder.

Navigation out of the entry is root-absolute. `href="../"` measured to `https://chat.padiem.net/apps/`
(404) from this two-level path, and `test_every_relative_reference_of_the_entry_page_resolves_in_the_staged_tree`
now refuses any `../` reference in the entry page. Live HTTP codes for the served entry are recorded
on #5937 rather than claimed here.

## 5. Reserved prerequisites — not closable inside an app PR

Recorded as open work with their owners, not as this contract being incomplete:

1. **A true separate origin.** Not adopted: the first release is same-origin by owner decision
   (header). Revisit only through *either* zone/custom-domain routing on the PADIEM host
   (Production configuration; owner decision, not code) *or* a new inbound identity lane on the
   Chat Worker. Inbound non-cookie authentication is an established shape here
   (`oracle_mesh_read_return_routes.py:397-405` `X-Oracle-Mesh-Secret` + `hmac.compare_digest`,
   `desktop_conversation_routes.py:89-91,172-206` device-session authority,
   `android_auth_routes.py:117-128` handoff secret), **but** each such route is individually
   reviewed: `PADIEM_PRODUCT_ACCESS_PROJECTION_4546_20261013.md:98` requires separate CENTRAL
   review for anything mounted in `app_factory.py`, and `same_origin_guard.py`/
   `session_revocation_guard.py` carry explicit, enumerated exemption classes (C/D) rather than a
   blanket internal exemption.
2. **A canonical product id for an app.** `identity_authority_worker.py:27` admits exactly
   `{"b62", "b54-padiem-claw"}` and `:167-170` raises unless the Production environment matches
   that set **exactly**. Adding a product is a Control Plane code change plus a matching
   Production environment value, together, in one reviewed release. Until then an app runs on the
   `b62` lane it already uses.
3. **A `product_scope` per app.** `history.py:113-115` admits `b62-chat` and `b66-quote`;
   `_require_product_scope` refuses anything else on every conversation path. The column carries
   no CHECK constraint (`migrations/042_conversation_product_scope.sql`), so this is Python + a
   reviewed migration mirror, not a schema rewrite. `dispatch_preinstruction.py:61-67`
   (`_PRODUCT_LABELS`) refuses an unregistered product when building the dispatch identity, so a
   new scope needs both. Until then the app's turns land in the Chat scope — which is why
   independent history/quotas per app are **not** delivered by this contract.
4. **Per-app usage accounting.** `UsageGate.authorize(raw_ip, user_id)` has no product dimension
   (`usage_gate.py:380`, `migrations/005_live_usage_quota.sql:6-13`), so an app sharing the lane
   shares Chat's counters. That is not a leak and not double-counting, but it is not isolation
   either; it is recorded rather than implied.
5. **Business number.** Nothing in `BUSINESS_REGISTRY.md` or
   `apps/portfolio-console/business-manifest.js` reserves one for the council apps or an app
   family, and the app on `main` registers none. Registration follows
   `BUSINESS_REGISTRY.md` §9 and must update `business-manifest.js`,
   `business-identity-core.js` and the parity test together
   (`apps/portfolio-console/tests/test_business_registry.py:83-95`).

## 6. Responsibility split, so the layer stays common

| Layer | Owned by | Contents |
| --- | --- | --- |
| Platform contract | CENTRAL via this document + the checker in `.github/scripts/padiem_apps_integration_contract.py` | route set, work-scope acceptance, origin/session rules, storage media and ceilings, the forbidden list |
| App work logic | each app, in its own `apps/<app>/**` | screens, prompt templates, per-tool state, its own CI lane and tests |

An app adds nothing to the platform to use it. Adding a **new app** means: its own directory, its
own path-filtered CI lane following `erp-item-master-ci.yml` (own paths **plus an enumerated list**
of shared files, never a package glob), and calls limited to §3. Adding a **new work identifier**
means one PR touching `WORK_SCOPES` in the checker, `_UTIL_SCOPES` in `request_contract.py`, the
refusal message the checker pins, and the app module that sends it — so the platform and the app
cannot disagree about the accepted set.

## 7. Verification

```text
python .github/scripts/padiem_apps_integration_contract.py check     → PADIEM_APPS_CONTRACT=EXACT
python .github/scripts/padiem_apps_integration_contract.py describe  → the machine-readable surface
python -m pytest .github/tests/test_padiem_apps_integration_contract.py
python -m pytest apps/padiem-chat/tests/test_b62_app_entry_staging.py  → the /apps/council/ staging
python -m pytest apps/padiem-chat/tests/test_5942_oauth_return_target.py  → the signed OAuth continuation
python -m pytest apps/padiem-council-apps/tests  → the entry's own behaviour, incl. in-page sign-in
```

The tests are refusal tests: a widened work-scope set, a removed refusal, a softened calendar
guard, an origin expectation read from the request, a session projection that starts carrying a
user id, a changed storage ceiling or media set, a missing platform route, and an enlarged identity
allowlist each make CI fail. `test_b62_app_entry_staging.py` adds the §4.4 entry to the same shape:
a staging level that no longer matches the entry page's own `./static/…` references, an app file
that would overwrite a Chat asset, an app source that stops shipping a required file, and a copy
committed under `apps/padiem-chat/**` each fail the build. Nothing in this contract is exercised
against a live provider or Production surface, and this document claims no live verification.
