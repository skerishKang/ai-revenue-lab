# Engine D1 migrations 0009–0013: read-only plan (#5359)

Status: preparation only. This PR does not implement or authorize a production
apply path. Do not dispatch any production mutation from this work.

- 0009: creates the XLSX read-tool continuation table and expiry index.
- 0010: creates the separate quote-write continuation table and expiry index.
- 0011: creates owner-scoped durable Agent run lease/checkpoint table and indexes.
- 0012: creates the durable tool-result ledger table and its run/expiry indexes.
- 0013: recreates the Agent run table to replace the 0–64 checkpoint check
  with a nonnegative, unbounded check; rows are copied and indexes recreated.

0013 copies then drops the original table; it must preserve every existing row,
indexes and all dependent data under concurrent writers. D1 does not disable
foreign-key enforcement with PRAGMA foreign_keys=OFF inside transactions:
https://developers.cloudflare.com/d1/sql-api/foreign-keys/
Inbound references, triggers, backup/restore access, snapshot integrity and
concurrent writes must be resolved in a tested apply design before any apply.

After this workflow has been merged, read-only classification can be dispatched
from main with the exact current full SHA (requires production environment
access and a Cloudflare token that can read the Engine Worker and D1):

    gh workflow run b54-engine-d1-0009-0013-readonly.yml --ref main -f target_sha=<40-character-current-main-sha>

Inspect the run with gh run view and its logs. It verifies the main revision,
account, Worker binding and database ID, then prints EXACT/MISSING/DRIFT,
existing table row counts and the run-table index list. DRIFT fails the job
after reporting available counts; it does not repair anything. EXACT for 0011
accepts either the original schema or the 0013-widened successor. A MISSING
table has no row count. No row contents or credentials are printed.

An approved future apply gate must re-read main and schema immediately before
mutation, skip already exact migrations, export and securely retain a verified
backup before 0013, compare the copied rows in a transaction without revealing
content, check all response blocks, verify post-apply schemas and indexes,
and document a tested, separately authorized restore procedure. D1 Time Travel
restore overwrites the database and may discard later writes; it must not be
automatically invoked: https://developers.cloudflare.com/d1/reference/time-travel/
