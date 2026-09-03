# B54 Notion Connector Safety v1

Status: repository-side preparation  
Parent: #1643  
Implementation: #1682  
Notion verification date: 2026-09-03

## Provider truth

Current official hosted Notion MCP uses `https://mcp.notion.com/mcp` with user OAuth. Notion documents OAuth 2.0 Authorization Code + PKCE for custom MCP clients and recommends Streamable HTTP; SSE remains a fallback. Hosted MCP uses the connected user's Notion access and can read/write accordingly.

Padiem therefore does **not** equate a successful Notion OAuth connection with whole-workspace model visibility.

## Current tool surface

Reviewed read-oriented hosted MCP tools include:

```text
notion-search
notion-fetch
notion-get-comments
notion-get-teams
notion-get-users
notion-get-user
notion-get-self
notion-query-data-sources
notion-query-database-view
```

Some query tools depend on the user's Notion plan/features. Current mutation-oriented tools include create/update/move/duplicate page operations plus database/data-source/view and comment mutations.

Unknown/new tools remain material/write-classified until reviewed.

## Scope

`NotionScopeProjection` creates a Padiem-side resource allowlist over exact resource-kind + resource-ref pairs:

```text
page:<ref>
database:<ref>
data_source:<ref>
view:<ref>
```

Database and data-source identities are deliberately distinct. The 2025 API split is not collapsed.

Hosted MCP search may have broader provider-side visibility through the user OAuth grant, but model-facing search hits are filtered against the Padiem resource allowlist before context exposure.

Linked/mentioned resources do not expand Padiem scope automatically.

## Content boundary

`NotionContentProjection` keeps bounded untrusted content with exact resource identity, `last_edited_at`, content SHA-256, linked refs and `in_trash` state.

Model projection:

- requires exact binding/workspace/resource scope;
- hides out-of-scope linked refs;
- caps content at 40,000 characters;
- marks content as untrusted external data.

## Mutation capabilities

Padiem semantic capabilities are independent from provider tool names:

```text
notion.create_page
notion.update_page
notion.move_page
notion.duplicate_page
notion.create_comment
notion.create_database
notion.update_data_source
notion.create_view
notion.update_view
notion.trash_page
notion.restore_page
```

Notion API version 2026-03-11 uses `in_trash`; request-side `archived` is deprecated/removed for current semantics. Permanent page deletion is not modeled because Notion API does not support it.

## Stale-state safety

Existing-resource mutations may bind to an exact `notion-state:<sha256>` derived from:

```text
resource identity
last edited timestamp
content SHA-256
in_trash state
```

Before mutation, `notion_mutation_preflight()` compares the latest trusted resource projection. Mismatch fails as `STALE_STATE` rather than silently overwriting newer user edits.

This is a Padiem preflight check; it does not claim provider-side atomic compare-and-swap unless a specific live provider surface proves it.

## P01 approval/evidence

Every material mutation binds:

```text
connector_id = notion
tool_name = exact Padiem semantic capability
target_ref = exact target/parent-derived target
payload_fingerprint = exact material fingerprint
expected_version_ref = notion-material:<fingerprint>
approval_ref = exact P01 approval
evidence_ref = exact P01 evidence
```

Changing target, parent, title, content hash, properties hash, expected state or trash/restore state changes the material fingerprint and invalidates prior approval.

## OAuth and credentials

Hosted MCP OAuth/token refresh belongs to trusted connector authority, not B54 task/model state. Raw access/refresh tokens never enter these contracts.

Current Notion hosted MCP does not support file upload. If file upload is needed, it must use a separately reviewed Notion file-upload API adapter rather than pretending hosted MCP supports it.

## Non-claims

```text
OFFICIAL_HOSTED_MCP = YES
USER_OAUTH_PKCE = YES
WHOLE_WORKSPACE_MODEL_VISIBILITY = NO
RESOURCE_ALLOWLIST = YES
LINKED_SCOPE_ESCAPE = NO
DATABASE_DATA_SOURCE_DISTINCT = YES
CURRENT_TRASH_FIELD = in_trash
PERMANENT_DELETE = NO
RAW_OAUTH_TOKEN_IN_B54 = NO
REAL_NOTION_MCP_CONFIGURED = NO
REAL_NOTION_MUTATION_CONFIGURED = NO
PRODUCTION_MUTATION = NO
```

## Live gate still required

#1643/#1569 remain responsible for real OAuth/account binding, live `tools/list` reconciliation, allowlist onboarding UX, bounded read/search canary, stale-state readback, separately approved write/trash/restore canaries, provider receipts, revocation and rollback/readback evidence.
