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

The existing `kagent` Python import name, Windows Run key, mutex, profile
directory and DPAPI credential binding are intentionally **not renamed**.
Brand changes are not permission to rekey a device or bypass authorization.

Live enrollment remains disabled until the protected TLS/WSS gateway and a
reviewed real-device release have been validated. Contract/mock tests alone do
not demonstrate a production connection.
