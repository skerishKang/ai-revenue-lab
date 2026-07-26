# Code Structure and Asset Versioning Policy

- Status: portfolio operating policy
- Owner: Web CTO
- Applies to: every AI Revenue Lab Business, product workspace, UI reference, portal surface, platform module, script, and test suite
- Effective for: newly created files and future material changes
- Related index: `docs/operations/README.md`

## 1. Decision

Every new AI Revenue Lab project and Business must follow three default rules:

1. browser-served local assets use deterministic version query strings;
2. newly authored source files do not exceed 500 physical lines;
3. code is separated into domain- or responsibility-based folders with explicit folder and file names.

These are maintainability and release-safety rules. They do not authorize broad refactors of stable existing code solely to satisfy formatting targets.

## 2. Asset version query strings

### 2.1 Required scope

Local browser assets loaded through stable URLs must use a version query when stale caching could serve old code or styles.

Mandatory by default:

- CSS files;
- JavaScript or TypeScript browser bundles;
- worker or browser modules loaded by HTML;
- replaced images, fonts, manifests, or other static assets that retain the same public path.

Example:

```html
<link rel="stylesheet" href="./styles.css?v=world-feed-20260726-1">
<script src="./app.js?v=world-feed-20260726-1" defer></script>
```

Do not add version queries to ordinary navigation URLs, API semantics, database identifiers, or user-generated links.

### 2.2 Version token rules

The token must be:

- deterministic;
- fixed in committed source;
- changed whenever the referenced asset bytes change;
- shared consistently across assets released as one visual or runtime revision;
- free of random values or request-time timestamps.

Accepted token strategies:

```text
<product-slug>-<YYYYMMDD>-<sequence>
```

Example:

```text
personal-edition-20260726-2
```

or a deterministic content identifier such as the first 12 lowercase hexadecimal characters of a SHA-256 digest when the product already uses content-hash versioning.

Do not mix unrelated token strategies within one product without a documented migration.

### 2.3 Update discipline

When a versioned asset changes:

1. update the asset;
2. change its version token in every relevant loader or template;
3. preserve required load order;
4. verify that old unversioned references are absent;
5. verify that stale cached assets cannot mask the change;
6. update focused contract tests where practical.

Changing HTML without changing the referenced asset does not require a token bump. Changing the asset while leaving the old token is a release defect.

### 2.4 Static references

For plain HTML/CSS/JavaScript references without a build system, hard-code the release token in HTML.

Do not introduce a framework, bundler, or deployment script merely to generate a query string.

## 3. Maximum source-file size

### 3.1 Default limit

A newly authored source file must contain no more than **500 physical lines**.

The limit applies to authored:

- HTML and templates;
- CSS and preprocessors;
- JavaScript and TypeScript;
- Python;
- shell and deployment scripts;
- configuration code;
- tests and test helpers;
- other executable or interpreted source files.

Five hundred lines is a ceiling, not a target. Split earlier when responsibilities are already separable.

### 3.2 Recommended split point

At approximately 350–400 lines, the implementer should check whether the file contains more than one responsibility and plan a safe split before it crosses 500 lines.

### 3.3 Existing oversized files

Existing files already above 500 lines are grandfathered.

For those files:

- do not fail unrelated work solely because the file already exceeds the limit;
- do not increase the file further without explicit justification;
- prefer extracting the responsibility being materially changed when the extraction is safe and in scope;
- do not perform a risky broad refactor merely to reduce line count;
- record the existing line count and any increase in the PR evidence;
- create a separate remediation issue when decomposition is necessary but outside the current task.

The exception applies to pre-existing code, not to a newly created oversized replacement file.

### 3.4 Generated and non-authored exceptions

The 500-line limit does not apply to:

- lock files;
- generated code;
- vendored third-party code;
- machine-generated snapshots or fixtures;
- data exports;
- migration output that must remain atomic for the framework.

These files must live in clearly identified generated, vendor, snapshot, fixture, data, or migration locations. Do not manually place ordinary authored application logic there to bypass the limit.

### 3.5 Exception procedure

A new authored source file above 500 lines requires an explicit exception before merge. The PR must state:

- exact file and line count;
- why safe decomposition is not currently possible;
- why the file is not generated or vendored;
- risks introduced by the exception;
- owner and follow-up issue;
- target decomposition boundary.

Convenience, worker speed, or “single-file demo” is not sufficient justification.

## 4. Folder and file organization

### 4.1 Organize by product domain or responsibility

Use folders that identify what the code owns, not when or by whom it was created.

Prefer:

```text
apps/<product-slug>/
├─ app/
│  ├─ feed/
│  ├─ stories/
│  ├─ personalization/
│  └─ shared-ui/
├─ static/
│  ├─ styles/
│  │  ├─ tokens.css
│  │  ├─ layout.css
│  │  └─ components/
│  └─ scripts/
│     ├─ feed/
│     └─ story/
└─ tests/
   ├─ feed/
   └─ story/
```

A product may use framework-specific directories, but the same ownership principle applies.

### 4.2 Naming conventions

Default naming:

- product and general web folders: `kebab-case`;
- HTML, CSS, JavaScript, TypeScript, and asset files: `kebab-case` unless the framework requires another convention;
- Python modules and packages: `snake_case`;
- classes and exported types: follow the language's established convention;
- test file names: mirror the source responsibility they verify;
- versioned or phased references: include the stable Business/product slug rather than vague chronology.

Prefer names such as:

```text
feed-state.js
story-detail-view.js
personalization-explanation.css
test_story_permissions.py
```

Avoid names such as:

```text
new.js
final.js
final-final.js
temp.py
misc.css
utils2.js
app-old.js
fixes.js
```

A generic `utils`, `helpers`, or `common` file must remain small and narrowly defined. When it begins collecting unrelated behavior, split it by domain.

### 4.3 One primary responsibility per file

Each authored file should have one clear reason to change.

Examples:

- tokens separate from page layout;
- shared components separate from page-specific composition;
- API routes separate from domain services;
- persistence separate from presentation;
- validation separate from provider calls;
- fixtures separate from production logic;
- browser state separate from DOM rendering when both become substantial.

### 4.4 Product boundaries

Product-specific code remains inside the approved product workspace.

Do not place product logic in another Business folder to reuse an existing deployment or structure. Cross-product extraction belongs in `platform/` only after demonstrated reuse and an approved architecture decision.

## 5. Verification requirements

Each implementation PR should report:

- new and materially changed source files with line counts;
- any existing files already above 500 lines;
- confirmation that no new authored source file exceeds 500 lines;
- folder and file organization rationale for new modules;
- version-query tokens added or bumped;
- proof that old or unversioned local asset references are absent where required;
- focused tests or static checks for asset versioning and file boundaries where practical.

Recommended automated checks:

- fail on newly added authored source files above 500 lines;
- report, but do not automatically fail unrelated changes because of grandfathered oversized files;
- verify required CSS/JS loaders contain deterministic `?v=` tokens;
- verify changed cache-sensitive assets receive corresponding token updates;
- exclude declared generated, vendor, lock, snapshot, fixture, data, and migration paths.

## 6. Review verdicts

Use these findings during review:

- `STRUCTURE_PASS`
- `STRUCTURE_NEEDS_SPLIT`
- `NEW_FILE_OVER_500_BLOCKED`
- `EXISTING_OVERSIZED_FILE_RECORDED`
- `ASSET_VERSION_PASS`
- `ASSET_VERSION_MISSING`
- `ASSET_VERSION_STALE`
- `NAMING_NEEDS_CORRECTION`

A visually correct or test-passing change may still be blocked when it creates an unversioned browser asset, a newly authored file over 500 lines, or an undifferentiated file/folder structure.

## 7. Governing rule

For new work, design the folder structure before writing a large file. Do not wait until one file exceeds 500 lines and then treat decomposition as optional.

For existing oversized code, preserve behavior first, avoid further growth, and decompose through focused, separately reviewable changes rather than a broad cleanup mixed into unrelated product work.