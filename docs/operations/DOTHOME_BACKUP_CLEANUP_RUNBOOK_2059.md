# Dothome Backup and Cleanup Runbook (issue #2059)

## Authority

Issue: #2059 — prepare a safe backup/inventory path before cleaning up the Dothome
hosting account that currently reports roughly **811 MiB used of a 1 GiB quota**,
almost entirely from legacy homepage files.

This runbook is the operating authority for that cleanup. It defines what the
Dothome account is allowed to hold, the backup-first rule, and the exact order in
which work may proceed.

```text
ACT-0_STATUS = READY (this document + scripts/ops/dothome_inventory.py)
ACT-1_STATUS = NOT_STARTED (backup + download, owner performs)
ACT-2_STATUS = NOT_STARTED (inventory review + owner-approved deletion)
```

## Purpose

Reclaim close to 1 GiB of Dothome capacity without losing anything the company
still needs, by replacing "delete and hope" with:

```text
BACKUP FIRST
→ LOCAL INVENTORY (report only)
→ OWNER REVIEW OF THE REPORT
→ OWNER-APPROVED DELETION
→ RE-VERIFY padiem.net STILL SERVES THE LANDING PAGE
```

## What the Dothome account is for

Dothome is a small shared-hosting account attached to the `padiem.net` domain.
Its role is deliberately narrow:

| Allowed | Not allowed |
| --- | --- |
| The static `padiem.net` landing site (`index.html` + CSS/JS/assets) | Padiem Chat or Claw user file storage |
| Small static marketing assets referenced by that landing | Connector secrets, OAuth material, API keys, tokens |
| Legacy homepage copies **only inside the dated local backup**, not on the host | Private generated documents under the public web root |
| | Anything reachable as `http(s)://padiem.net/<path>` that must not be public |

Two hard consequences follow:

1. **Dothome must not become private user storage for Padiem Chat / Claw.**
   User uploads belong in the product's own storage, never in the hosting web root.
2. **No credential is ever stored under the public web root.** If a credential is
   found there during inventory, treat it as exposed: rotate first, then delete.

## Backup-first rule

No file may be deleted from the Dothome account until a verified local copy
exists. The order is mandatory and cannot be rearranged:

1. Download the full hosting content to the local backup path below.
2. Verify the download (file count and total bytes are plausible; spot-open the
   landing `index.html`).
3. Run the local inventory on the downloaded copy.
4. Review the report with the owner.
5. Only then delete, and only the paths the owner explicitly approved.

## Local backup path convention

```text
<backup-volume>/padiem-dothome/<YYYY-MM-DD>/
├── html/                  # verbatim copy of the hosting document root
├── inventory.json         # output of scripts/ops/dothome_inventory.py
└── inventory.md           # human-readable output of the same run
```

Rules:

- One dated directory per cleanup attempt. Never overwrite a previous backup.
- The scan root passed to the inventory script is the **`html/` directory**, not
  the dated parent: the report paths then match the hosting paths exactly.
- The backup directory itself must never be the scan root of a second run, so a
  previous backup is never proposed as a delete candidate of the new one.
- Google Drive is **optional**, for off-site redundancy only. If used, upload the
  dated directory as a single archive after step 2. It is not a substitute for
  the local copy and never holds credentials in plaintext.

## Inventory before delete

`scripts/ops/dothome_inventory.py` inspects an **already-downloaded local
directory**. It is read-only by construction:

```text
MODE              = REPORT_ONLY
NETWORK_CALLS     = 0
HOSTING_LOGIN     = NO
DELETE_PERFORMED  = NO
CREDENTIAL_READ   = NO
SYMLINK_FOLLOWING = NO
```

It refuses dangerous scan roots: empty input, relative paths, a filesystem root,
the user home directory, the user profile directory, a symlinked root, a missing
path and a non-directory path. Refusal exits with code `2` and prints
`DOTHOME_INVENTORY_ERROR=<reason>`.

Safe invocation:

```bash
python scripts/ops/dothome_inventory.py \
  --root "<backup-volume>/padiem-dothome/2026-09-07/html" \
  --out-json "<backup-volume>/padiem-dothome/2026-09-07/inventory.json" \
  --out-md   "<backup-volume>/padiem-dothome/2026-09-07/inventory.md" \
  --quota-mb 1024 \
  --large-threshold-mb 10
```

The report contains, in this order: a summary with running totals, per-directory
sizes, files above the threshold, archives, media, old build/junk directories,
duplicate groups with the space their extra copies hold, the **protected current
landing files**, and the delete candidates with a reason per file.

## Protection rule for the current landing

The inventory treats every `index.html` / `index.htm` it finds as a candidate
current landing document, and follows its `href`, `src` and `srcset` references
plus the `url(...)` references inside referenced CSS. Every file reachable that
way is added to `landing.protected`.

**A protected file is never emitted as a delete candidate**, even when it is an
image, an archive, oversized, inside a build directory, or a duplicate of
another file. Over-protection is the intended failure direction: losing the live
landing page costs far more than leaving a few hundred KiB behind.

Because every `index.html` is protected, a legacy `2019_homepage/index.html`
that survives the cleanup stays protected until the owner says otherwise. The
owner must name the real document root during review rather than relying on the
script's guess.

## Delete requires owner approval

The report is evidence, not authority. Deletion happens only when:

1. The owner has read `inventory.md` (or `inventory.json`).
2. The owner has named the real document root and confirmed the protected set.
3. The owner has listed the exact paths or categories to delete.
4. A verified backup exists for the same date.
5. Deletion is followed by a live check that `padiem.net` still serves the
   landing page.

Delete in small batches, largest-first, and re-run the inventory after each
batch so the remaining size is always measured rather than assumed.

## Final target

```text
QUOTA_BYTES            = 1073741824  (1 GiB)
START_USAGE            ≈ 811 MiB
TARGET_RECLAIMED       ≈ 1 GiB worth of capacity freed
TARGET_REMAINING       = the current landing site only (single-digit MiB)
```

The report's `projected_remaining_bytes` is the honest projection: it is the
total minus every candidate byte, and it is an upper bound on the reclaim
because the owner may reject individual candidates.

## ACT-0 scope (this change)

In scope: this runbook and the local, read-only inventory script plus its tests.

Explicitly **not** in ACT-0:

- No connection to the Dothome account (no FTP/SFTP/HTTP, no credentials).
- No download or upload of real hosting data.
- No deletion of anything, local or remote.
- No change to `padiem.net`, Cloudflare, R2, D1 or any production system.

ACT-1 (owner) downloads the account to the local backup path. ACT-2 runs the
inventory on that download and performs owner-approved deletion.

## Verification

```bash
python -m py_compile scripts/ops/dothome_inventory.py
python -m pytest -q scripts/ops/tests/test_dothome_inventory.py
```

The tests cover: totals and per-directory sizes, large-file detection, archive
and media detection, old build/junk directory detection, hash-based duplicate
detection, landing reference detection, protected files never appearing as
candidates, the tree being byte-identical after a scan, rejection of dangerous
roots, symlinks recorded but not followed, deterministic output, the CLI writing
JSON and Markdown, and a source-level assertion that the script contains no
network use, no deletion call and no credential lookup.
