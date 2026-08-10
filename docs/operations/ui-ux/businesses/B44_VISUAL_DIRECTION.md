# B44 — Portfolio Console Visual Direction

Status: `DIRECTION_FROZEN_WITH_LIVE_CAPTURE_BLOCKER`  
Verdict: `KEEP_PRODUCT_ROLE · LIVE_CONFORMANCE_PENDING`

`OWNER_UI_APPROVED=false` remains unchanged.

## Authority

Current main manifest resolves B44 to:

```text
product = Portfolio Console
workspace = apps/portfolio-console/
canonical = https://ai-revenue-portfolio-console.pages.dev/
```

B56 is an intentional numbering gap, not B44's successor.

## Fresh audit blocker

Dedicated run `31424158017`, artifact `9076523288`, digest `sha256:28b69985d24cf6022ffe20f1d6136e60dff52b7fbf343f21ed1f10885ed2f7d2` could not render the product because Cloudflare redirected the headless runner to a `dash.cloudflare.com` security-verification challenge.

The captured page was **not** the Portfolio Console and therefore is not accepted as visual evidence. Exact Desktop/Mobile product conformance remains pending until the live challenge can be bypassed legitimately or the owner/browser can access the canonical surface normally.

## Product thesis

Portfolio Console is the owner-facing truth/navigation layer for all numbered Businesses: current lifecycle, visual-review authority, external/successor boundaries and direct surface access.

Core object: **the portfolio business list + authoritative status/action for each Business**.

## Reserved territory — Portfolio Operations Index

- dense but highly scannable numbered business list
- status/authority/boundary visible without opening every row
- direct live/review/external action
- clear owner-review state separated from historical technical phase evidence
- search/filter/navigation prioritized over decorative visual identity

Avoid redesigning it as a marketing portfolio, gallery of screenshots or dark control tower. It is operational truth infrastructure.

## Preserve

- numbered identity
- portfolio truth layer
- external/integrated successor boundaries
- owner visual status distinct from historical UI/UX technical status
- direct launch behavior
- no accidental creation of missing internal products

## Acceptance criteria for later live recheck

1. Desktop can scan many Businesses quickly;
2. Mobile rows retain number, identity, status and primary action without clipping;
3. external/successor items are unmistakable;
4. owner-review vs approved vs not-applicable is truthful;
5. search/filter/action controls are obvious;
6. no horizontal overflow or sticky chrome obstruction;
7. Cloudflare security challenge is not mistaken for product QA evidence.
