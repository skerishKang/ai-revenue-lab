# B54 Dropbox Connector Safety v1

Status: repository-side preparation  
Parent: #1644  
Implementation: #1685  
Dropbox verification date: 2026-09-03

## Provider truth

Dropbox API access is rooted in an authorized namespace. Team members may have different home and root/team-space namespace IDs. Team Space calls require the caller to preserve the intended `Dropbox-API-Path-Root` semantics; relying on display paths or an old member-root assumption can lose or misaddress team content.

Padiem therefore binds Dropbox resource authority to:

```text
trusted connector binding
Padiem workspace/account
access model
root namespace
home namespace
stable resource id + namespace
```

Display paths are metadata only.

## Access models

Repository contracts distinguish:

```text
APP_FOLDER
FULL_DROPBOX
TEAM_SPACE
```

Use App Folder when it satisfies the product workflow. A broader Full Dropbox/team-space OAuth grant never means all accessible content should be placed into model context.

No recursive whole-tree synchronization/crawl is enabled by this contract.

## Resource scope

`DropboxScopeProjection` has an explicit allowlist of stable `DropboxResourceRef` values:

```text
<namespace>:file:<provider id>
<namespace>:folder:<provider id>
```

The same provider id/name in another namespace is not the same authorized resource.

Cross-namespace move/copy is not enabled by this initial contract. It needs a separately reviewed provider operation and scope rule instead of silently widening authority.

## Metadata and content evidence

`DropboxMetadataProjection` records bounded metadata:

- stable resource ref;
- display path/name as non-authoritative metadata;
- size;
- file `rev`;
- Dropbox provider `content_hash`;
- modified timestamps;
- deleted state.

Important terminology:

```text
Dropbox content_hash != ordinary SHA-256(file bytes)
```

Dropbox content hash uses the provider's documented block-hash construction. Padiem names it `provider_content_hash` and never labels it SHA-256. A separate local SHA-256 may be used for Padiem payload/evidence when needed.

## Mutation capabilities

Semantic Padiem capabilities:

```text
dropbox.upload_add
dropbox.update_file
dropbox.copy
dropbox.move
dropbox.delete
```

Read capability remains separate.

### New upload

`UPLOAD_ADD` requires an exact allowed parent folder + target filename + payload SHA-256. It does not carry an existing revision and does not silently mean overwrite.

### Existing-file update

Dropbox supports provider-side optimistic concurrency through `WriteMode.Update(rev)`: the overwrite succeeds only when the supplied `rev` matches the current server revision.

Padiem requires:

```text
exact file resource
expected_rev
strict_conflict = true
current trusted metadata rev == expected_rev
```

The `ConnectorWriteIntent.expected_version_ref` binds a SHA-256 of the expected provider revision. The raw provider revision remains in the trusted adapter/material boundary.

This is stronger than the Drive preflight-only version check because Dropbox exposes a provider-side exact-revision update mode.

### Move/copy/delete

Move and copy bind exact source + exact allowed destination parent + destination name. Delete binds the exact source. Destructive actions remain P01 approval material and are not implied by connection/OAuth possession.

## Approval and evidence

Every mutation binds:

```text
connector_id = dropbox
tool_name = exact semantic capability
target_ref = exact namespace/resource target
payload_fingerprint = exact material fingerprint
expected_version_ref = exact rev hash for update, otherwise material version
approval_ref = exact P01 approval
evidence_ref = exact P01 evidence
idempotency_key = exact write key
```

Changed target, content, destination, revision or conflict policy changes the material fingerprint/version binding.

## Provider receipt

A trusted write receipt may record:

- exact approved target;
- result stable resource ref;
- result `rev`;
- result Dropbox `content_hash`;
- provider operation/evidence refs.

Generated model text is not mutation evidence.

## Non-claims

```text
OFFICIAL_DROPBOX_API = YES
PATH_ROOT_EXPLICIT = YES
APP_FOLDER_PREFERRED_WHEN_SUFFICIENT = YES
WHOLE_ACCOUNT_MODEL_VISIBILITY = NO
DISPLAY_PATH_IS_AUTHORITY = NO
WHOLE_TREE_SYNC = NO
UPDATE_MODE = exact rev
STRICT_CONFLICT = YES
PROVIDER_CONTENT_HASH_IS_SHA256 = NO
RAW_OAUTH_TOKEN_IN_B54 = NO
REAL_DROPBOX_OAUTH_CONFIGURED = NO
REAL_DROPBOX_MUTATION_CONFIGURED = NO
PRODUCTION_MUTATION = NO
```

## Live gate still required

#1644/#1569 remain responsible for:

1. real Dropbox OAuth/app selection and least-privilege scopes;
2. exact account/root/home namespace readback;
3. App Folder vs Full Dropbox/team-space onboarding decision;
4. resource allowlist UX;
5. bounded list/read/download canary;
6. quarantine/content-hash evidence;
7. exact-rev stale update negative canary and successful update canary;
8. separately approved upload/copy/move/delete canaries;
9. provider receipt/readback;
10. revocation and rollback/recovery verification.
