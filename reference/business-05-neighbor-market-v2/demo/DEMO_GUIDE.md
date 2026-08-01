# Neighbor Market Demo Guide

## Run

Open `index.html` directly, or serve the demo directory with a static server:

```bash
python -m http.server 4175 --bind 127.0.0.1
```

Then open:

```text
http://127.0.0.1:4175/index.html
```

The demo requires no backend, package installation, build command, database, account, or API key.

## Recommended 7-minute demonstration

### 1. Product premise — 1 minute

Open Home and point to the fixed relationship order:

1. current apartment;
2. nearby apartments;
3. general neighborhood businesses.

Explain that the service is not primarily a nearby-shop directory. It helps residents discover resident-operated work first.

### 2. Resident discovery — 2 minutes

- Search for `반찬` or choose a category.
- Switch among all three relationship filters.
- Open a listing detail.
- Favorite the listing.
- Simulate an order, reservation, quote, or consultation request.
- Open `찜·요청` and show that the state changed locally.

State clearly that no request was sent or saved.

### 3. Listing-owner flow — 2 minutes

Switch to `사업자` demo mode.

- Open registration.
- Choose relationship type first.
- Edit the synthetic details.
- Preview the listing.
- Submit the review simulation.
- Show the owner dashboard status.

### 4. Operator flow — 1.5 minutes

Switch to `운영자` demo mode.

- Open the review queue.
- Inspect `우리집 정리수납`.
- Show the separation between public reason and internal-note placeholder.
- Simulate approve or request changes.
- Return to owner mode and show the updated demo status.

### 5. Limitations — 30 seconds

Explain that the demo has no real authentication, resident verification, persistence, messaging, payment, or management-office endorsement.

## Reset

Use `데모 초기화`, or refresh the page.
