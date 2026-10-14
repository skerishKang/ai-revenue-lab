# PADIEM Connector

PADIEM Connector is the Windows PC connection program for PADIEM products.
The supervised local execution runtime is **PADIEM Agent**.

Official CLI: `padiem-connector` (Node wrapper) or `python -m padiem_connector`
(Python). Former `claw-connect` and `python -m claw_connect` are compatibility
aliases that run the **same** product and preserve device identity.

## Windows installation

Run `install.ps1` in a reviewed release directory. The Start Menu shortcut
is **PADIEM Connector**. `-Autostart` is refused without a real committed
device credential. The installer does not require administrator privileges and
never creates a second Resident, account or Broker.

Normal installation now requests an immediate launch of the visible system
tray, even before server enrollment has been authorized. It stays UNREGISTERED
until the existing Identity/Broker registration is verified and never declares
a PC online just because the installer started a process. Only after a valid,
durable device binding is committed can the existing Windows logon autostart
default activate. The tray lets the user turn autostart ON or OFF; durable OFF
remains effective across reboots, app updates and reinstalls. Exit remains
accessible from the tray. This source change does not itself implement the
web-session-to-native automatic account handoff or a standalone Windows EXE.

The existing `kagent` Python import name, Windows Run key, mutex, profile
directory and DPAPI credential binding are intentionally **not renamed**.
Brand changes are not permission to rekey a device or bypass authorization.

Live enrollment remains disabled until the protected TLS/WSS gateway and a
reviewed real-device release have been validated. Contract/mock tests alone do
not demonstrate a production connection.

## Agent availability check (read-only)

Run `python -m padiem_connector doctor` (or `padiem-connector doctor`).
It checks the pinned PADIEM Agent source root without launching the Agent,
creating device identity, reading credentials, enabling autostart or contacting
Cloudflare. A nonzero exit means that the Agent source is not ready.

Install against an existing, trusted Agent source with `install.ps1 -AgentSrc
<full path to apps/korean-ai-code-agent/src>`. The older `-ResidentSrc` option
remains accepted. A caller-supplied path must contain the canonical `kagent`
Resident, pairing and protected-storage modules; otherwise the installer
refuses before modifying the existing installation. Without an explicit pin,
the diagnostic reports whether the interpreter already has the canonical
Agent source installed. A successful Connector install alone is **not** a
claim that the Agent or production Broker is connected.

Upgrade/uninstall retains the legacy `claw_connect` command when removing an
old installation that has no `padiem_connector` Python entrypoint yet.


## Source-only WSS socket implementation (#4139)

Review code: claw_connect.review_wss_transport. It constructs a genuine
websockets 17.2 asyncio client with verified OS CA and DNS hostname (TLS >=
1.2), fixed outbound wss://chat.padiem.net/api/claw/connector/gateway/session,
no auto-redirects (even same host), no ambient proxy or browser headers, no
frame logging, no automatic replay and bounded message sizes. Its isolated
test dependency is in requirements-wss-review.txt. The hosted Windows
contract CI installs that pinned review dependency and tests the hardening
without opening any real socket.

Normal user installation intentionally does NOT bundle a networking library
or activate this adapter. The default CLI, login, enrollment, tray and
autostart continue to fail closed and are NOT made production-live by this
source-only change. The Cloudflare Worker must independently prove trusted
ingress and the PADIEM operator must verify identity/Broker consent and
two-PC restart tests before production release.
