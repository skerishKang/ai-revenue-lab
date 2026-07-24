# AI Revenue Lab Portfolio Console

Private, static administrator dashboard for reviewing every numbered AI Revenue Lab Business from one screen.

This is **not** the user-facing `apps/portal/` product. It is an internal operator surface that shows only non-secret portfolio metadata and links to independently deployed Business surfaces and GitHub evidence.

## Current capabilities

- Business-number and title-first registry table;
- search, lifecycle-state filtering, and sorting;
- demo-readiness progress and next-action queue;
- selected-Business detail panel;
- verified surface, pull-request, and issue links;
- reserved slots through Business 15;
- data-driven expansion for Business 16 and later;
- dark AI/operations-console visual system;
- no external API, cookies, browser storage, or secrets.

## Run locally

```bash
cd apps/portfolio-console
python -m http.server 4173
```

Open `http://127.0.0.1:4173`.

## Update a Business

Edit only `businesses.js`. Add or modify one object. The table, metrics, detail panel, filters, and priority queue are derived from the data.

Do not add credentials, API keys, private hostnames, user data, database URLs, or unaudited deployment claims.

## Deployment boundary

The page has no application authentication. If deployed, place the Cloudflare Pages project behind **Cloudflare Access** or an equivalent private access gate.

The included `_headers` file disables caching, framing, forms, external connections, and permission-gated browser capabilities.

## Validation

```bash
node --check businesses.js
node --check app.js
python -m unittest discover -s tests -v
```
