# B54 Google Drive Scope + Write Safety v1

Status: repository-side preparation  
Parent: #1637  
Implementation: #1660  
Google Drive API verification date: 2026-09-03

## Current source contract

The first read adapter came from the selective OpenBot reuse slice and remains the
physical read baseline. This extension adds Padiem-specific resource authorization,
Shared Drive bounds and write conflict evidence.

Official Google references reviewed for this slice:

- `https://developers.google.com/workspace/drive/api/guides/enable-shareddrives`
- `https://developers.google.com/workspace/drive/api/reference/rest/v3/files`
- `https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update`
- `https://developers.google.com/workspace/drive/api/guides/manage-revisions`

## Resource scope

`DriveScopeProjection` requires at least one explicit boundary:

```text
allow_my_drive_root
allowed_shared_drive_ids
allowed_file_ids
allowed_folder_ids
```

There is no implicit `allDrives` mode.

A trusted `DriveResourceProof` combines exact file metadata with ancestor folder ids.
Authorization succeeds only when the exact binding matches and one of the explicit
resource boundaries matches.

Trashed files fail closed.

### Folder selection

An allowed folder authorizes:

- the selected folder itself; and
- a resource whose trusted ancestor proof contains that exact folder id.

The model does not get to assert ancestry. The trusted Drive adapter/authority must
resolve it from provider metadata.

### Shortcut rule

A shortcut is never content authority.

```text
shortcut allowed by its own location
  -> SHORTCUT_TARGET_REQUIRED
  -> target id must exactly match shortcutDetails.targetId
  -> target receives a new independent DriveResourceProof
  -> target must independently be in scope
```

A shortcut placed inside an allowed folder therefore cannot smuggle in an unrelated
target from outside the allowed boundary.

## Shared Drive support

Current Google Drive v3 documentation requires/uses Shared Drive aware requests and
supports exact-drive search with:

```text
supportsAllDrives=true
includeItemsFromAllDrives=true
corpora=drive
driveId=<exact approved shared drive>
```

`shared_drive_list_query()` emits exactly that narrow shape and refuses a drive id
not present in the trusted scope. `corpora=allDrives` is not used by default.

The existing Drive read adapter now also:

- marks file list/get metadata calls as Shared Drive aware;
- excludes trashed resources from list/search;
- retrieves `driveId`, `parents`, `version`, checksums, `headRevisionId`, `resourceKey`
  and shortcut target metadata;
- refuses direct content reads of trashed files;
- refuses shortcut content reads until an independently-authorized target is used.

## Version and conflict safety

Google's File resource exposes a monotonically increasing `version` that reflects
server-side changes. Current Drive v3 `files.update` documentation does not expose an
atomic expected-version / compare-and-swap parameter.

Therefore Padiem explicitly separates two claims:

```text
VERSION_PRECHECK = SUPPORTED
ATOMIC_VERSION_CAS = NOT CLAIMED
VERSION_POSTCHECK = SUPPORTED
```

### Preflight

`DriveWritePrecondition` binds:

- exact file id;
- expected Drive version;
- optional modified time;
- optional MD5/SHA-256 checksum;
- optional binary head revision id.

The shared `ConnectorWriteIntent` must also contain:

```text
connector_id = google-drive
target_ref = exact file id
expected_version_ref = drive-version:<expected version>
P01 approval_ref
evidence_ref
idempotency_key
payload_fingerprint
```

Before a physical write, `drive_write_preflight()` refuses:

- wrong binding/target/version binding;
- out-of-scope resource;
- trashed resource;
- shortcut used as the write target;
- already changed version/modified/checksum/revision metadata.

### Race limitation

A provider-side change can theoretically occur after preflight and before an update
if the provider does not offer an atomic conditional update primitive for the used
operation. Repository code must not describe this preflight as a CAS guarantee.

This limitation is why a Production write needs provider receipt evidence and a
post-write metadata read.

### Post-write verification

`drive_write_postcheck()` requires:

- exact connector/binding/idempotency/target receipt match;
- exact returned file id;
- returned Drive version strictly greater than the preflight version;
- trusted receipt `version_ref` exactly equal to `drive-version:<returned version>`.

Model text never counts as write success.

## Remaining external gates

This slice does not make #1637 Production-complete.

Still required:

1. trusted Google OAuth/account binding through Control Plane/connector authority;
2. real read canary with an explicitly scoped account/folder/file/Shared Drive;
3. durable trusted ancestry/resource proof implementation;
4. physical create/update/copy/upload adapter behind P01 approval;
5. real write canary with preflight + receipt + post-write readback;
6. rollback/recovery evidence where the chosen write operation supports it.

```text
DRIVE_SCOPE_CONTRACT_READY = YES
DRIVE_SHARED_DRIVE_SUPPORT_CONTRACT_READY = YES
DRIVE_ATOMIC_VERSION_CAS_SUPPORTED = NO
DRIVE_VERSION_PRECHECK_SUPPORTED = YES
DRIVE_VERSION_POSTCHECK_SUPPORTED = YES
REAL_GOOGLE_DRIVE_OAUTH_CONFIGURED = NO
REAL_GOOGLE_DRIVE_WRITE_CONFIGURED = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
