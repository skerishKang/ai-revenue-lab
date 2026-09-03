# B54 Google Calendar Mutation Safety v1

Status: repository-side preparation  
Parent: #1641  
Implementation: #1666  
Google verification date: 2026-09-03

## Provider truth

Current Google Calendar Workspace MCP `/mcp/v1` publishes:

```text
create_event
delete_event
get_event
list_calendars
list_events
respond_to_event
search_events
suggest_time
update_event
```

The Calendar MCP surface remains Developer Preview.

Current MCP mutation schemas expose notification-level semantics. A calendar mutation
can therefore cause attendee email notifications; that effect is approval material,
not an implementation detail.

Google Calendar Event resources expose ETags. Google Calendar REST supports
conditional modification using `If-Match`; if the ETag changed, the provider returns
HTTP 412 rather than silently overwriting the newer resource.

Important distinction:

```text
Google Calendar REST If-Match support = verified
Calendar MCP update_event If-Match atomicity = not yet verified
```

B54 must not infer the second statement from the first. A live MCP tool-list/schema
and mutation canary must prove equivalent stale-write behavior before the MCP path is
allowed to claim atomic ETag protection.

Official Google references reviewed:

- Calendar MCP configuration/tool reference
- Calendar MCP `create_event`, `update_event`, `respond_to_event`
- Calendar API resource versioning / ETag conditional modification
- Calendar API recurring-event guidance
- Calendar API event creation / attendee notification behavior

## Calendar scope

`CalendarScopeProjection` contains an exact trusted binding/workspace plus an explicit
allowlist of calendar IDs. Connecting a Google account does not mean every calendar
is automatically model/tool scope.

```text
CALENDAR_SCOPE_BOUNDED = YES
WHOLE_ACCOUNT_CALENDAR_ACCESS = NO
```

## Event time

`CalendarEventTime` requires an explicit IANA timezone for every event material
snapshot.

### Timed event

Requires:

```text
all_day = false
start_at = timezone-aware datetime
end_at   = timezone-aware datetime
time_zone = explicit IANA zone
```

The canonical fingerprint uses UTC instants plus the declared timezone name, so a
change in either instant or intended zone is material.

### All-day event

Requires:

```text
all_day = true
start_date = inclusive date
end_date   = exclusive date
time_zone   = explicit IANA zone
```

Timed and all-day representations cannot be mixed.

## Recurrence target

A mutation must identify its recurrence target explicitly:

```text
NON_RECURRING
SERIES
INSTANCE
```

An `INSTANCE` requires both:

```text
recurring_event_id
original_start_key
```

This mirrors Google's recurring-event identity model where `recurringEventId` plus
`originalStartTime` identifies the occurrence even when that occurrence was moved.

A request to change one occurrence must never silently become a whole-series update.

## Untrusted Calendar content

`CalendarEventProjection` carries bounded event metadata, but summary, description,
location, attendee content and recurrence text are external data.

```text
EVENT_CONTENT_TRUSTED = NO
```

The raw provider ETag is retained only inside the trusted adapter/projection boundary.
The model-facing safe projection exposes only `etag_sha256`, never the raw ETag.

## Mutation capabilities

Padiem separates:

```text
CREATE_EVENT
UPDATE_EVENT
DELETE_EVENT
RESPOND_TO_EVENT
```

Read and `suggest_time` do not imply any mutation capability.

Every mutation uses the shared M0 `ConnectorWriteIntent` and P01 approval/evidence
authority.

## Material fingerprint

`CalendarMutationMaterial` binds the approval to:

- trusted binding/workspace;
- exact calendar ID;
- exact operation;
- existing event ID where applicable;
- expected ETag SHA-256 where applicable;
- summary;
- description SHA-256;
- location;
- attendee emails;
- all-day/timed boundaries and timezone;
- recurrence target;
- recurrence rules;
- reminder policy;
- conference policy;
- notification level;
- attendee-email side-effect boolean;
- response status for invitation responses.

Changing any of those fields changes the deterministic `material_fingerprint` and
invalidates an older approval.

## Attendee notification side effect

Notification level is explicit:

```text
NONE
EXTERNAL_ONLY
ALL
```

No hidden provider-default notification authority is allowed. If attendees exist and
the level is `EXTERNAL_ONLY` or `ALL`, the material snapshot states:

```text
attendee_notification_side_effect = true
```

That bit is part of the approved fingerprint.

For new Meet conferences, Padiem uses a semantic policy of creating a new conference
rather than reusing an unrelated existing Meet code.

## Existing-event stale-write protection

Update/delete/respond material requires:

```text
event_id
expected_etag_sha256
```

and the write intent must bind:

```text
connector_id = google-calendar
tool_name = exact Calendar mutation capability
target_ref = calendar:<calendar_id>:event:<event_id>
payload_fingerprint = exact material fingerprint
expected_version_ref = calendar-etag:<etag_sha256>
approval_ref = exact P01 approval
evidence_ref = exact P01 evidence
idempotency_key = exact write key
```

`calendar_mutation_preflight()` rechecks the current trusted event projection. If the
current ETag hash is different, the decision is:

```text
STALE_ETAG
```

For a direct Calendar REST physical adapter, the same raw trusted ETag must also be
sent using HTTP `If-Match`. A 412 means the write is refused and the event must be
re-read before any new approval.

Repository preflight alone is not a substitute for provider-side conditional
modification.

## Create-event binding

Create has no pre-existing ETag. It uses:

```text
target_ref = calendar:<calendar_id>:new
expected_version_ref = calendar-create:<material_fingerprint>
```

After creation the trusted provider receipt must identify the newly returned event and
returned ETag evidence.

## Mutation receipt

`CalendarMutationReceipt` wraps the shared `ConnectorWriteReceipt`.

For create/update/respond, a trusted result ETag hash is required. Delete does not
invent a returned Event ETag when the provider operation does not return one.

```text
provider receipt = mutation evidence
model text       != mutation evidence
```

## Remaining external gates

#1641 remains open until:

1. trusted Google Calendar OAuth/account binding is live;
2. bounded calendar list/event read canary passes;
3. live `suggest_time` behavior is reconciled and no fabricated availability is
   accepted;
4. Calendar MCP live tool-list/schema is reconciled against the pinned source
   contract;
5. create/update/delete/respond mutation canaries pass behind P01 approval/evidence;
6. attendee notification behavior is verified for each chosen notification level;
7. recurring series vs instance canaries verify exact target behavior;
8. direct REST ETag `If-Match` path or an equivalently proven MCP atomic path prevents
   stale overwrite;
9. disable/recovery/rollback operational evidence is complete.

```text
CALENDAR_SCOPE_BOUNDED = YES
ALL_DAY_TIMED_EXPLICIT = YES
TIMEZONE_EXPLICIT = YES
RECURRENCE_TARGET_EXPLICIT = YES
ATTENDEE_NOTIFICATION_SIDE_EFFECT_BOUND = YES
P01_MUTATION_APPROVAL_REQUIRED = YES
CALENDAR_REST_IF_MATCH_SUPPORTED = YES
CALENDAR_MCP_ETAG_IF_MATCH_ATOMICITY_VERIFIED = NO
STALE_ETAG_WRITE_ALLOWED = NO
EVENT_CONTENT_TRUSTED = NO
REAL_GOOGLE_CALENDAR_OAUTH_CONFIGURED = NO
REAL_GOOGLE_CALENDAR_MUTATION_CONFIGURED = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
