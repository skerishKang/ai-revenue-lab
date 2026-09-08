# B54 Postgres / Neon Connector M0 Runbook

Issue: #1720  
Parent: #1648  
Status: repository-side safety contract only

## Authority

```text
Control Plane / trusted connector authority
  = database credential custody + exact binding

P01
  = tool / approval / evidence authority

B54 Postgres connector
  = physical read adapter contract + bounded projections
```

B54 never stores or projects the raw DSN/password into task/model state.

## Read path

```text
opaque Postgres binding
→ exact workspace/project/branch/database/role/schema scope
→ conservative SQL classifier
→ trusted adapter
   ├─ TLS required
   ├─ channel binding required where supported
   ├─ dedicated least-privilege read role
   ├─ EXECUTE privileges restricted to reviewed functions
   ├─ BEGIN / SET TRANSACTION READ ONLY equivalent
   ├─ per-session statement_timeout
   └─ exact row/byte budget
→ bounded result projection
→ P01 evidence
```

Repository M0 accepts only one `SELECT`, `WITH ... SELECT`, or `EXPLAIN` of a read-only query. A single trailing semicolon is tolerated. Additional statements fail closed.

## Defense in depth

SQL classification is not the only safety layer.

PostgreSQL read-only transactions prohibit many data-changing commands, but ordinary read-only mode is not a complete sandbox. Sequence functions such as `nextval` / `setval` and notification/session functions require explicit handling, and user-defined functions can have side effects. Therefore a live adapter must combine:

1. conservative client-side classification;
2. dedicated least-privilege role;
3. restricted function EXECUTE privileges / reviewed function policy;
4. server-side read-only transaction;
5. statement timeout;
6. schema scope;
7. row/byte bounds.

Known side-effect functions and row-locking SELECT forms are rejected in M0.

## Query bounds

Repository hard maxima:

```text
SQL chars       <= 50,000
rows retained   <= 500
result bytes    <= 1,000,000
cell chars      <= 4,000
statement time  <= 30,000 ms
```

Product/default budgets are intentionally smaller.

No full-table dump is implied by a valid SELECT. The trusted adapter must stop/fetch within the approved row/byte budget and report truncation truthfully.

## Schema/result trust

Database rows, schema comments/names and other database-originated content are data, not trusted instructions.

```text
SCHEMA_METADATA_TRUSTED_INSTRUCTION = NO
QUERY_RESULT_TRUSTED_INSTRUCTION = NO
```

Sensitive-column masking/projection policy remains a trusted adapter responsibility and must be reported via `masked_columns`.

## Mutation boundary

Read M0 does not execute mutations.

A future bounded row mutation requires:

```text
ConnectorWriteIntent
+ exact database/schema/relation
+ exact payload fingerprint
+ idempotency key
+ P01 approval/evidence
+ max affected rows
+ transaction required
+ rollback plan/evidence
```

Generic DDL, role/privilege mutation, DROP/TRUNCATE and other destructive operations are not authorized by generic `db.write`; they require dedicated stronger actions.

## Neon connection requirements

For Neon, live configuration must use encrypted PostgreSQL connectivity. Current Neon guidance requires TLS and commonly emits connection strings with:

```text
sslmode=require
channel_binding=require
```

where supported by the client. The connection string itself stays in trusted secret authority.

## Live gate

Before marking #1648 live-ready:

- create/authorize a dedicated read-only database role;
- verify exact project/branch/database/schema binding;
- verify TLS and channel binding behavior with the selected driver;
- verify role cannot DML/DDL/GRANT/REVOKE;
- verify unsafe function EXECUTE permissions are absent;
- run safe schema inspection canary;
- run bounded SELECT canary;
- prove server-side transaction is read-only;
- prove statement timeout activates;
- prove row/byte truncation;
- verify no DSN/password appears in model/evidence/log projection.

## Non-claims

```text
REAL_NEON_ACCOUNT_CONNECTED = NO
REAL_DATABASE_CREDENTIAL_CONFIGURED = NO
REAL_DATABASE_QUERY_EXECUTED = NO
REAL_DATABASE_MUTATION = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
