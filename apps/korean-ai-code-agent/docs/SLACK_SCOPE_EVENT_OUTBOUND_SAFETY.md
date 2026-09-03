# B54 Slack Scope + Event + Outbound Safety v1

Status: repository-side preparation  
Parent: #1642  
Implementation: #1670  
Slack verification date: 2026-09-03

## Provider truth

Current Slack MCP server uses JSON-RPC 2.0 over Streamable HTTP at:

```text
https://mcp.slack.com/mcp
```

Slack requires an MCP client to be backed by a registered Slack app. Slack documents
confidential OAuth for user-token MCP access. OAuth/client secrets remain owned by the
trusted connector authority, never by B54 task/model state.

The Slack MCP tool surface is evolving. Slack added new MCP tools during 2026, so B54
must not assume an old static tool list is complete.

Current repository posture remains:

```text
STATIC_READ_TOOL_ALLOWLIST_CONFIGURED = NO
LIVE_TOOLS_LIST_REQUIRED_FOR_READ_CLASSIFICATION = YES
UNKNOWN_MCP_TOOL_FAILS_CLOSED = YES
```

This means a new or unknown Slack MCP tool remains material/write-classified until a
reviewed live `tools/list` reconciliation explicitly approves its effect.

Official Slack references reviewed:

- `https://docs.slack.dev/ai/slack-mcp-server/`
- `https://docs.slack.dev/authentication/verifying-requests-from-slack/`
- `https://docs.slack.dev/apis/events-api/`
- Slack 2026 MCP tool changelog

## Workspace and channel scope

`SlackWorkspaceScope` binds:

- opaque trusted connector binding;
- workspace ref;
- exact Slack `team_id`;
- exact Slack app id;
- explicit channel allowlist;
- explicit subset of private channels.

Connecting a Slack workspace does not grant whole-workspace history access.

```text
WORKSPACE_CONNECTION_IMPLIES_ALL_CHANNELS = NO
PRIVATE_CHANNEL_ACCESS_IMPLICIT = NO
```

A private channel must be both in the general channel allowlist and in the explicit
private-channel subset.

## HTTP Events API ingress

Slack signs HTTP requests with:

```text
X-Slack-Signature
X-Slack-Request-Timestamp
```

Slack recommends rejecting a request timestamp that differs by more than five minutes
to reduce replay risk.

B54 does not own the signing secret. The trusted ingress/connector authority performs
HMAC verification and projects only the verified result into the shared M0
`ConnectorInboundEvent` contract.

`SlackInboundEventProjection` then additionally requires:

- connector id = `slack`;
- signature verification required;
- signature freshness window <= 300 seconds;
- exact binding/workspace;
- exact Slack team id;
- exact Slack app id;
- exact allowed channel when a channel is present;
- private-channel explicit scope when applicable.

Slack Events API `event_id` is globally unique. Slack may retry a failed delivery up
to three times and exposes retry metadata, so the shared M0 replay guard/durable
Production equivalent must deduplicate the event id before processing.

Mentions such as `@padiem` may create intake, but:

```text
mention_grants_tool_authority = false
```

Message/event bodies remain untrusted external data.

## Message and thread context

`SlackMessageProjection` keeps exact:

- workspace ref;
- channel id;
- message timestamp;
- optional thread timestamp;
- attributed user ref;
- bounded text;
- bounded file manifests.

Repository context bound:

```text
MAX_SLACK_MESSAGE_CHARS = 20,000
WHOLE_WORKSPACE_DUMP = NO
```

Slack message instructions never become system/tool authority.

## Files and quarantine

A `SlackFileManifest` contains metadata only until content quarantine succeeds.
Raw file bytes never automatically enter model context.

Accepted file material requires:

```text
quarantine_state = accepted
sha256 = exact digest
quarantine_evidence_ref = trusted evidence
```

Repository quarantine ingress is capped at 10 MiB per file and eight files per bounded
action. Those are Padiem safety limits, not claims about Slack provider limits.

## Outbound capabilities

Padiem semantic capabilities are deliberately independent of whatever physical Slack
MCP/Web API tool name is eventually selected:

```text
slack.post_message
slack.reply_thread
slack.update_message
slack.upload_file
```

This prevents a provider tool rename or newly added MCP tool from silently changing
P01 authority.

No autonomous bulk-message or user-impersonation capability is defined.

## Outbound material fingerprint

`SlackOutboundMaterial` binds:

- exact binding/workspace/team/app;
- semantic capability;
- exact channel;
- text SHA-256;
- exact thread timestamp for a reply;
- exact message timestamp for an update;
- exact approved file ref/name/MIME/size/SHA-256/quarantine evidence for uploads;
- authenticated-actor-only semantics;
- bulk send = false.

Capability target refs are separate:

```text
post   -> slack:<workspace>:channel:<channel>:new-message
reply  -> slack:<workspace>:channel:<channel>:thread:<thread_ts>:reply
update -> slack:<workspace>:channel:<channel>:message:<message_ts>
upload -> slack:<workspace>:channel:<channel>:upload
```

Changing text, target, thread/message identity or approved file material changes the
deterministic fingerprint and invalidates old approval.

## P01 outbound preflight

The shared `ConnectorWriteIntent` must bind:

```text
connector_id = slack
tool_name = exact Padiem semantic capability
target_ref = exact Slack target ref
payload_fingerprint = exact material fingerprint
expected_version_ref = slack-material:<material fingerprint>
approval_ref = exact P01 approval
evidence_ref = exact P01 evidence
idempotency_key = exact write key
```

`slack_outbound_preflight()` rechecks workspace/app/channel scope, exact semantic
capability, target, approval/evidence, fingerprint and material version.

OAuth possession alone is not outbound authority.

## Trusted receipt

`SlackOutboundReceipt` wraps the shared `ConnectorWriteReceipt` and requires the
provider receipt target to equal the exact approved target.

Message post/reply/update operations require a returned message timestamp. File upload
requires returned provider file refs.

```text
provider receipt = delivery/mutation evidence
model text       != delivery evidence
```

## Remaining external gates

#1642 remains open until:

1. registered Slack app + trusted per-user OAuth binding is live;
2. live MCP `tools/list` is reconciled and exact read tools are reviewed;
3. bounded public/private channel read canaries pass;
4. HTTP Events API signing-secret verification is wired in trusted ingress;
5. event-id durable dedupe/retry handling is live;
6. selected file download/quarantine canary passes;
7. post/reply/update/upload physical tool mappings are reconciled;
8. P01-approved outbound canaries produce trusted provider receipts;
9. revoke/disable/recovery behavior is verified.

```text
OFFICIAL_SLACK_APP_BOUNDARY = YES
WORKSPACE_APP_BOUND = YES
CHANNEL_ALLOWLIST = YES
PRIVATE_CHANNEL_IMPLICIT = NO
REQUEST_SIGNATURE_BOUNDARY = YES
FIVE_MINUTE_REPLAY_WINDOW = YES
EVENT_ID_DEDUPE = YES
INBOUND_UNTRUSTED = YES
WHOLE_WORKSPACE_DUMP = NO
FILE_QUARANTINE = YES
POST_REPLY_UPDATE_UPLOAD_SEPARATE = YES
OUTBOUND_P01_APPROVAL = YES
STATIC_READ_TOOL_ALLOWLIST_CONFIGURED = NO
UNKNOWN_MCP_TOOL_FAILS_CLOSED = YES
AUTONOMOUS_BULK_MESSAGE = NO
USER_IMPERSONATION = NO
RAW_SLACK_TOKEN_IN_B54 = NO
REAL_SLACK_OAUTH_CONFIGURED = NO
REAL_SLACK_MUTATION_CONFIGURED = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
