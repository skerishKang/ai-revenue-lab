# Hark #3580: real Engine ToolRuntime Office LIST/READ confirmation registration

Date: 2026-10-10. Registration milestone, not production Owner→Resident Office E2E.

## New Engine capabilities

Two distinct canonical `ToolRuntime` registrations are added with `ApprovalPolicy.USER_CONFIRMATION` and registered scope `filesystem.read`: (a) `local.filesystem.list.quote-candidates` for metadata-only nonrecursive selected-root XLS/XLSX candidates; (b) `local.filesystem.read` for a single explicit root-relative XLS/XLSX filename. The two have separate ToolSpec IDs and separate approval pauses; one approval is not reusable for the other.

The bounded schemas prohibit unexpected browser/model arguments, any entire-PC scan, recursive enumeration, directory delete or elevation. The READ schema is direct basename only; paths with `/` or `\\`, traversal or absolute Windows paths are refused. The user confirmation handler emits only `intent_confirmed` and its canonical request SHA256 reference and explicitly reports `file_read_executed=False`, `resident_dispatched=False`, `drive_write=False`. No raw path, workbook bytes, OAuth or device secrets are retained in the result.

The registered tools use the existing Core Engine USER_CONFIRMATION pause and AuthenticatedFirstPartyApprovalDecisionVerifier, not new fake VerifiedApprovalDecision objects. A real approved first-party decision permits the deterministic ToolRuntime confirmation handler to run once and consumes its canonical continuation; it does **not** grant a Windows file read. Core scope propagation and trusted server-side run ID correlation are supplied by merged PR #4202.

## Default deployment

Shipped Engine resolver is unchanged unless a deployment-owned `PADIEM_ENGINE_HARK_OFFICE_P01_ENABLED=1` explicitly registers the bounded Office tool binding. Product UI/browser/model content cannot switch it. Production enablement is deliberately OFF until exact owner/Broker/Resident grant transfer and device-bound evidence are available. There is no Production/Secrets modification.

## Focused proof

Real Core/Engine ToolRuntime: LIST and READ separately pause and produce exact registered scope; confirmed user decision via first-party Engine verifier allows only deterministic confirmation handler with no filesystem/Drive activity; missing granted scope, extra arguments, absolute or traversal READ paths refuse; continuation cannot be reused. Existing Engine approval smoke remains unaffected. Tests 12 PASS.

## Still required

1. B62 trusted source binds verified conversation owner, workspace, currently selected root and device to live Broker command and an Engine P01 pause. No user-provided scope, run ID or filename should override it.
2. Authenticated server-to-device one-shot TTL transfer of that exact first-party verified LIST decision and separately approved READ decision, including fingerprint/selected candidate identity/command ACK. Do not use test-loopback #3140.
3. Shipped Windows Resident must consume that evidence with existing `P01LocalPermissionWindowsFileAuthorizationPort`, select root and process real Office XLSX→PDF and `.xls` preserve-original workflows. Then Broker can return the already merged owner-only Hark PDF preview. Separately consented Drive WRITE is not a default side effect.

Keep #3580/#3933/#3936 OPEN; no production deployment, secrets, paid model, Drive writes, or user data mutation.