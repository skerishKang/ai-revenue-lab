# Validation record

Validation target: exact generated static source state.

## Browser environment limitation

The browser administrator policy blocked both `http://127.0.0.1` and `file://` navigation (`ERR_BLOCKED_BY_ADMINISTRATOR`). Validation therefore used Playwright `page.set_content()` with the same HTML, CSS, JavaScript and SVG bytes loaded into an in-memory document. This is **local in-memory document validation**, not localhost hosting and not Hosted URL verification. No public deployment claim is made from this evidence.

## Required states

- `today`
- `listening`
- `sources`
- `script`
- `letter`
- `archive`
- `mobile`

## Automated browser checks

The evidence script validates:

- 1440×1100, 768×1024 and 390×844 viewports;
- horizontal overflow equals 0;
- seven state controls and seven state panels;
- synthetic source and voice disclosure;
- deterministic CSS/JS version query;
- visible keyboard focus;
- console and page errors equal 0;
- failed local assets equal 0;
- external runtime requests equal 0;
- Chapter Pulse timing and stable scroll/focus;
- reduced-motion final state.

## Repository checks

- all files remain under `reference/business-18-personal-audio-channel-v1/**`;
- `git diff --cached --check` passes in the isolated validation repository;
- no `apps/**`, `docs/**`, workflows or other Business references are modified.

## Deployment boundary

Cloudflare deployment is a separate exact-head attempt. A missing authenticated deployment tool must be reported as `BLOCKED_NOT_DEPLOYED`; no URL or deployment ID may be fabricated.
