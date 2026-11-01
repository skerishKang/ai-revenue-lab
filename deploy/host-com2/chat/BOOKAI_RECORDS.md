# BookAI records on COM2

Code-only handoff for issue [#6446, protocol v1](https://github.com/skerishKang/ai-revenue-lab/issues/6446#issuecomment-6552411565).
Base: `25c4cb93a7a3aff3736ea96a25cbae730202d247`; branch: `feat/bookai-records-api-261101`.

- Public path: `https://chat.padiem.net/api/bookai/records`, through the existing front to COM2 Chat.
- Installed by `app.local_cpython.build_app` in host mode, using the existing Chat SQLite database and `SqliteD1` facade.
- Required secret name: `BOOKAI_COM2_SYNC_SECRET`, matching the BookAI Pages Worker. CTO configures it; no value is included here.
- Authentication reuses the app AI HMAC implementation in `app/com2_hmac.py`. The canonical message is `METHOD\nPATH\nTIMESTAMP\nSUBJECT\nSHA256HEX(BODY)`; PATH includes the exact query string, GET has an empty body, and the timestamp tolerance is 300 seconds.
- Only the verified `X-Bookai-Subject` determines record ownership. Cookies, query parameters and record payloads cannot select another owner.

## API

`GET ?since=<ms>&limit=<n>` defaults to since=0, limit=500, filters `updated_at > since` (the initial since=0 also includes legacy timestamp-zero records), and sorts by `updated_at, record_id`. It returns `{records, next_since, more}` including tombstones. Empty pages retain the supplied since. Larger limits are accepted so the existing app can overlap timestamp boundaries without losing equal-time records.

`POST {"records":[...]}` accepts up to 5MiB of UTF-8 JSON and returns `{accepted, kept_newer}`. A whole validated batch is one transaction. Conditional UPSERT keeps the larger modification time; equal times preserve the existing record and acknowledge an idempotent no-op. Deletes remain records with `deleted=true`. Duplicate IDs within a single batch are rejected. All responses are private/no-store.

The front never routes this endpoint to the old Cloudflare Chat backup. On COM2 failure it returns 503, allowing the app's existing durable queue to retry.

## Migration and CTO handoff

`apps/padiem-chat/migrations/082_bookai_records.sql` adds the subject/record primary key and a subject/time/record index.

Existing deployment selection already includes 082: `chat/install.sh` uses the checkout's migrations directory and `local_cpython.apply_migrations` discovers all pending `*.sql` files using its existing ledger. No fixed list requires an update.

`deploy_from_main.sh` also discovers 082 and deliberately stops with `MIGRATION_FIRST` (exit 3) while it is unapplied. CTO must follow the existing migration-first deployment procedure; this change does not bypass that gate or apply an operational migration.

Focused tests cover signatures, user isolation, atomic latest-write merging, tombstones, 5MiB boundaries, real app session/signing and sync pagination, host restart persistence, and migration discovery/idempotence. App integration uses synthetic authentication and a temporary SQLite database. No production secrets or deployment are used.
