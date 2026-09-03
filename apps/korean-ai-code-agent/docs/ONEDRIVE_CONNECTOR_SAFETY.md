# B54 OneDrive / Microsoft Graph Connector Safety v1

Status: repository-side preparation  
Parent: #1645  
Implementation: #1687  
Microsoft Graph verification date: 2026-09-03

## Provider truth

Padiem uses Microsoft Graph for OneDrive/SharePoint file access and keeps these product identities distinct:

```text
PERSONAL
BUSINESS
SHAREPOINT
```

A trusted binding preserves exact account, tenant (for work/school), site (for SharePoint), drive and DriveItem identities. Paths and names are metadata, not authority.

## Permission boundary

Padiem prefers the narrowest Graph permission mode that satisfies the workflow.

Relevant current Microsoft permission facts:

- `Files.ReadWrite.AppFolder` is a narrow app-root mode for personal Microsoft accounts.
- Selected permission families such as `Sites.Selected` / `Files.SelectedOperations.Selected` can constrain access to assigned resources.
- legacy delegated `Files.ReadWrite.Selected` is not the direct Microsoft Graph selected-file mechanism for new Graph calls.
- broad `Files.ReadWrite.All` / `Sites.ReadWrite.All` are not the Padiem default.

The provider grant is still not model visibility. `OneDriveScopeProjection` applies a separate explicit DriveItem allowlist before content becomes available to Claw tools/model context.

## DriveItem scope

Canonical resource identity is:

```text
<drive id>:file:<item id>
<drive id>:folder:<item id>
```

One scope cannot mix drive identities. SharePoint additionally requires exact tenant + site identity. Cross-drive move is rejected in this initial contract rather than silently broadening scope.

## Untrusted item metadata

`OneDriveItemProjection` keeps raw eTag/cTag only in the trusted adapter boundary. Model-safe output exposes SHA-256 fingerprints of those tags, not the raw values.

The projection also bounds file size/path/name and marks provider content as untrusted.

## Conditional mutation

Current Graph DriveItem update/move/delete and upload-session surfaces support `If-Match`; when the supplied eTag/cTag does not match, Microsoft Graph returns `412 Precondition Failed` instead of applying the mutation.

Padiem standardizes existing-resource mutation on the exact eTag:

```text
trusted current DriveItem eTag
 -> eTag SHA-256 in approved material
 -> current preflight compares latest eTag SHA-256
 -> trusted adapter sends raw current eTag as If-Match
```

Existing-resource capabilities requiring exact expected eTag:

```text
onedrive.update_content
onedrive.move
onedrive.delete
```

A stale tag fails closed before provider call, and the provider `If-Match` remains the final atomic conflict gate.

## New uploads and copy

New uploads bind exact allowed parent + filename + payload SHA-256. Initial Padiem conflict behavior is always:

```text
@microsoft.graph.conflictBehavior = fail
```

No implicit `replace` or `rename` is allowed. Provider support varies across account/product operations, so any broader conflict mode requires a separate reviewed capability.

Copy is treated as creation of a new target from an allowed source and destination. It does not modify the source item; provider-specific source-version guarantees must be proven separately if required by a workflow.

## Resumable upload sessions

Graph upload sessions expose an `uploadUrl` that functions as sensitive bearer-like write authority. B54 never stores or projects that URL into model/task state.

Instead, `OneDriveUploadSessionProjection` carries only an opaque trusted session ref, exact target, expiry and `defer_commit` flag.

Where `deferCommit=true` is selected, final materialization remains an explicit trusted commit step and must have receipt/readback evidence.

## P01 approval/evidence

Every mutation uses the shared M0 `ConnectorWriteIntent` and binds:

```text
connector_id = onedrive
tool_name = exact Padiem semantic capability
target_ref = exact DriveItem/parent-derived target
payload_fingerprint = exact material fingerprint
expected_version_ref = onedrive-etag:<etag hash> for existing mutation
approval_ref = exact P01 approval
evidence_ref = exact P01 evidence
idempotency_key = exact write key
```

Changing content, target, destination, eTag, conflict behavior or upload mode changes approval material.

## Receipts

Trusted receipts correlate the exact approved target and may expose safe fingerprints of resulting eTag/cTag plus returned DriveItem identity. Delete receipts cannot claim a live item tag.

Generated model text is never mutation evidence.

## Non-claims

```text
MICROSOFT_GRAPH = YES
PERSONAL_BUSINESS_SHAREPOINT_DISTINCT = YES
SELECTED_RESOURCE_SCOPE_PREFERRED = YES
LEGACY_FILES_READWRITE_SELECTED_FOR_DIRECT_GRAPH = NO
APP_FOLDER_PERSONAL_NARROW_MODE = YES
WHOLE_TENANT_MODEL_VISIBILITY = NO
PATH_IS_AUTHORITY = NO
IF_MATCH_ETAG = YES
NEW_UPLOAD_CONFLICT_DEFAULT = fail
RAW_UPLOAD_SESSION_URL_IN_B54 = NO
RAW_OAUTH_TOKEN_IN_B54 = NO
REAL_MICROSOFT_OAUTH_CONFIGURED = NO
REAL_ONEDRIVE_MUTATION_CONFIGURED = NO
PRODUCTION_MUTATION = NO
```

## Live gate still required

#1645/#1569 remain responsible for:

1. real Microsoft identity OAuth/app registration;
2. tenant/account/site/drive identity readback;
3. least-privilege Selected/AppFolder permission assignment where applicable;
4. item/folder allowlist onboarding;
5. bounded read/download/quarantine canary;
6. exact eTag stale negative canary (`412`) and successful update/move/delete canaries;
7. new upload conflict-fail canary;
8. resumable upload + opaque session + explicit commit/readback proof;
9. separately approved copy canary;
10. provider receipt, revocation and rollback/recovery evidence.
