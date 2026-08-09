# Business 17 · Local Shop Magazine

Phase 1 static visual reference for **우리 가게 매거진 / Local Shop Magazine**.

## Status

```text
UI_ONLY
UI_IMPLEMENTATION_READY_FOR_LOCAL_VALIDATION
NOT_VALIDATED_BY_LOCAL
NOT_DEPLOYED_PENDING_UI_APPROVAL
```

## Fixture

- Shop: 모서리 제과점 / Corner Oven — fictional
- Owner: 한서윤 — fictional
- Issue: 늦여름 무화과와 저녁 빵
- Every person, product, quote, event, customer and place detail is synthetic.

## Seven states

1. `cover`
2. `product`
3. `maker`
4. `neighbour`
5. `season`
6. `kit`
7. `mobile`

## Run

```bash
cd reference/business-17-local-shop-magazine-v1
python -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000/`.

## Review controls

- Click the seven state tabs.
- Use Left/Right Arrow keys.
- On the cover state, use `#replay-counter` to replay Counter-to-Page.
- Reduced motion is implemented in `styles/main.css` under `@media (prefers-reduced-motion: reduce)` and handled in `scripts/review.js`.

## Boundaries

No ecommerce, ordering, inventory, POS, coupons, loyalty, CRM, customer database, social connection, publishing, scheduling, analytics, authentication, persistence, payments or AI calls.
