# Web Claw is a locally executing AI agent (2026-10-20)

## Product and UX
PADIEM Web Claw is a **local computer AI agent controlled from a web interface**, not merely a cloud chatbot. The web surface provides conversation, connection controls, progress and receipt display. The authorized PADIEM Connector on the user's own device executes the local file, command and application operations. Server-resident features still execute in the server component explicitly responsible for them.

The intended setup experience is website -> **Connect computer** -> **Confirm** -> connected, without asking the user to run CMD, copy/paste device codes or repeatedly register an identity. This is product intent; never report connected if authentication or heartbeat failed.

## Content, secrets and authority
- An authorized user's own business material must remain available in its original form to the agent and that user; do not treat sensitive-looking customer names, quote amounts, bank details or provided credentials as grounds for silently redacting/refusing an authorized workflow.
- Credentials provided for a requested local operation may be used by the authorized local runtime. Prefer local credential storage and injection into the exact target tool over needlessly sending the literal secret to a remote model. B14 provider credentials remain in the existing Secrets Store. Do not echo tokens into diagnostics, shared transcripts or other users' outputs unnecessarily.
- Enforce account, workspace and device boundaries at the actual authenticated broker/connector execution path. A second user's account must not gain access to the first user's material. A browser page alone does not confer local machine authority.
- Do not import general public-web-chat input restrictions into local-agent operations by default; no invented customer prompts, content ceilings, forced redaction or approvals. Real provider, device, platform and authorization constraints still apply.

## Implementation checks
1. Trace the authenticated web -> broker -> connector -> local tool -> original conversation receipt path.
2. For each serializer, identify its actual audience: authorized user/model context, logs, telemetry, or third party. Preserve full content in authorized data paths, while keeping credential hygiene for external diagnostics.
3. Retain explicit no-cross-workspace tests, connected device/session checks and original-content preservation regressions.
4. Keep source implementation, CI, merge, deploy and authenticated live verification as distinct statuses.

Related tracking: #5360 (original memory), #5361 (redaction/refusal audit), #4379 (unrequested size and execution ceilings).

## PC file access: admitted plan ceiling and narrowing intent

- `ops` derives only from the admitted plan ceiling: `files_list` permits `['list']`; `files` permits `['list', 'read']`.
- Model `intent` may only narrow the current step: `list` restricts it to listing; `read` or omission has no effect; other values are refused.
- A list-only ceiling blocks read regardless of the model's intent, before any read dispatch.
- The admitted ceiling remains fixed for the run; subsequent model steps cannot widen it.
- Existing server authorization, workspace/device ownership, path and size checks remain mandatory; a model proposal grants no authority.
- Residual risk: a listing-only conversation can still receive a full plan, as in current production; #5574 alone does not classify that conversation.
- The #5573 second slice will select `files_list|files` in the first step of the existing #5597 B14 tool-calling channel, admit it in Engine before dispatch, and pass it unchanged through Chat, without a separate classifier or selection call.
- 2026-10-24 복원(#5653): 레인 진입은 임시 키워드 판정, Mesh 전용 대상 허용. 목표 설계는 PC_LANE_TARGET_DESIGN_20261024.md
