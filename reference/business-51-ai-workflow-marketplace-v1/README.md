# Business 51 · AI Workflow Marketplace

Phase 1 `UI_ONLY` static visual reference for Issue #303.

## Primary result

`HUMAN-APPROVED WORKFLOW MARKETPLACE LISTING`

## Exact states

`cover`, `package`, `workflow`, `compatibility`, `evidence`, `listing`, `mobile`

## Product boundary

The reference presents one wholly synthetic workflow package as a reviewable marketplace listing. It separates publisher claims from independent validation, current from deprecated versions, limited compatibility from universal compatibility, required from granted permission, safe trial from production approval, listed price from completed transaction, and marketplace approval from legal or security certification.

It performs no workflow execution, installation, account connection, permission grant, payment, publishing, storage, analytics, provider/model call, UX journey, or backend operation.

## Synthetic fixture

- Publisher: Daram Operations Studio — fictional
- Workflow: Supplier Quote Review Pack — synthetic
- Version: 1.4.0 — synthetic
- Deprecated version: 1.2.0 — synthetic
- Required permission: local file read only — not granted
- Listed price: ₩39,000 — synthetic
- Installation: not performed
- Execution: not performed
- Payment: not performed

## Local review

Serve this directory with a local static server and open `index.html`. The tablist supports click, Arrow keys, Home, End, Enter and Space. The listing panel includes the deterministic `Verified-Package-to-Marketplace-Listing` motion with actual final-element `animationend` completion authority.

Run:

```bash
node tests/static-contract.mjs
python tests/browser_validate.py
```

The browser validator uses local Chromium and validates the 7 × 3 viewport/state matrix, assets, network boundary, accessibility controls, motion timing, replay determinism and reduced motion.

## Final governance state

`PR_OPEN_DRAFT_UNMERGED` · `Issue OPEN` · `UX_NOT_STARTED` · `BACKEND_FROZEN` · `DO_NOT_MERGE`
