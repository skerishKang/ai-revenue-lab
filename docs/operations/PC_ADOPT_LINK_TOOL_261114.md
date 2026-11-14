# PC adopt tool (COM2, no browser) — 2026-11-14

`apps/padiem-chat/tools/adopt_pc_link.py` performs the after-admin-check part of
`/api/pc/pairings/adopt` directly on COM2, against the Chat service's own store.
It is for the QA account's PC link (for example COM2) when the operator does not
want to open a browser session.

## Run location

COM2, as root, with the Chat service's venv and the ops checkout:

```bash
sudo -u root /opt/padiem/chat-com2/venv/bin/python \
  /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/adopt_pc_link.py \
  --target-from-qa-env
```

The script requires `PADIEM_CHAT_CPYTHON_HOST=1` (it sets the default) and the
same env/DB the Chat service uses. The target account is read from
`/etc/padiem/qa-smoke.env` (root 0600); the file must exist, be root-owned and
mode 600. The account value is never printed.

## Preview (default) and apply

- Preview (no write):
  `... adopt_pc_link.py --target-from-qa-env`
- Apply (create the one link):
  `... adopt_pc_link.py --target-from-qa-env --apply`

Preview prints only:

```text
PC_FOUND=yes
PRESENCE=ok
TARGET_ACCOUNT=found
EXISTING_LINK=no
OTHER_ACCOUNTS_KEPT=1
```

Apply adds `ADOPTED=1`. If the link already exists, it prints `ALREADY_LINKED`
and writes nothing. The tool never prints the account id, mesh node id, token or
tag value.

## Stops

- not root → `STOP ROOT_REQUIRED`
- env file missing / not regular / not root:600 / empty → `STOP QA_ENV_*`
- PC label not found → `STOP PC_NOT_FOUND` (preview prints `PC_FOUND=no`)
- no executor receipt → `STOP PC_NOT_PRESENT` (preview prints `PRESENCE=none`)
- target account unknown → `STOP TARGET_ACCOUNT_UNKNOWN`
- more than one active link with the label → `STOP PC_AMBIGUOUS`
- queue-backed pairing store (no local DB) → `STOP PC_PAIRING_QUEUE_BACKEND_UNSUPPORTED`

## Rollback

The tool only creates a link; it does not revoke one. Revoke the target
account's link from the Chat PC list (or `DELETE /api/pc/pairings/{link_id}`
with that account's session). Revoking one link does not touch another
account's link on the same PC. The tool prints no link id, so find the link in
the account's PC list.

## Tests

`apps/padiem-chat/tests/test_adopt_pc_link_tool_261114.py` covers preview
(no write), apply (one link, other accounts kept), idempotent re-run, missing
PC, no presence, metadata stops, and output hygiene. The existing adopt route
tests (`test_5573_pc_pairing_admin_adopt.py`,
`test_6695_pr2_presence_owner_scope.py`) cover the route after the extraction.