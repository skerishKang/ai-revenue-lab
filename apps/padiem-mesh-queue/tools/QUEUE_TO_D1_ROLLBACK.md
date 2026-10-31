# Queue dispatch rollback export (#5881)

This offline utility prepares data; it does not apply SQL or switch the backend.
Use a consistent, access-controlled copy of the queue database (including WAL
state) and a **local SQLite copy of the intended D1 dispatch schema**. Apply the
actual Chat migrations to a disposable database for the schema copy; never point
the tool at production D1. Exported JSON and SQL contain dispatch paths and
commands: protect them as sensitive operational data and delete them under the
approved retention procedure. Do not paste their contents into logs or PRs.

1. Stop queue writes, including claims, renewals and result submissions.
2. Stop the executor. Reconcile any in-flight work and wait until every active
   claim lease has expired. A stopped executor alone is not proof of completion.
3. Export and verify against the same frozen snapshot:
   ```
   python apps/padiem-mesh-queue/tools/queue_to_d1.py export --queue queue-snapshot.sqlite --d1-schema d1-schema.sqlite --json dispatch.json --sql dispatch.sql
   python apps/padiem-mesh-queue/tools/queue_to_d1.py verify --queue queue-snapshot.sqlite --d1-schema d1-schema.sqlite --json dispatch.json --sql dispatch.sql
   ```
   Run with a command timeout of 60 seconds; failure or timeout stops rollback.
   Both commands report counts and active claim dispatch IDs, not row contents.
   A nonzero active-claim, result-in-progress, or legacy nonce-without-lease
   count means **do not apply**: reconcile and take a new
   snapshot after the claims expire, then export and verify with new file names.
   Repeat verify immediately before application; an expired row or changed source,
   schema, JSON or SQL causes failure. Do not apply stale or partially written files.
4. Apply the verified SQL **only through the existing protected D1 gate**. Its
   plain INSERTs deliberately fail on conflicting IDs or uniqueness constraints;
   do not replace or ignore conflicts. Verify the gate's result before proceeding.
5. Only after successful application and the authorized operational checks,
   switch `PC_QUEUE_BACKEND=d1` using the normal protected procedure.

Only unexpired pending rows without an active claim lease are exported; result-persistence states (received/store_failed), other states, expired rows and
active claims are counted separately. All owners are
included. A nonce and lease are preserved verbatim where the destination has
the corresponding columns. When a claim column is absent, the report names it
as omitted or initialized, respectively; check destination compatibility before
application. In particular, old D1 without `claimed_until` cannot re-deliver a
row with a preserved nonce: resolve that using the protected procedure rather
than silently clearing a nonce. A pending row with nonce but no lease is also
fail-closed in the D1 claim code, despite having no currently valid lease; it
requires reconciliation before rollback. No field such as `received_at` is
converted: unsupported schema or type differences stop the tool.
