# PADIEM Connector and PADIEM Agent — naming decision and compatibility

2026-10-13 KST · Issue #4139 · CENTRAL integration PR #4572

## Official names
- **PADIEM Connector**: the customer-facing PC installer, Start Menu
  shortcut, tray, CLI, and device-management surface.
- **PADIEM Agent**: the EXISTING local runtime/Resident executing under the
  trusted PADIEM server/Broker contracts.
- **padiem-connector**: primary CLI and npm bin entry; legacy
  `claw-connect` remains an alias to the identical Python implementation.
- **padiem_agent.resident**: public Python alias delegating to
  `kagent.local_agent_resident_process.main`; not another worker.

## Immutable migration identifiers
Do NOT rename these as cosmetic changes: `claw_connect` internal Python
package; `kagent` import namespace and Resident launch on existing hosts;
`PadiemClawConnect` HKCU Run value and owner's durable OFF choice;
`PadiemClawConnect.SingleInstance.v1` mutex;
`PadiemClawConnect.QuitEvent.v1` event;
`Padiem/ClawConnect` installation/state root and existing DPAPI binding.
Changing these silently could create duplicate PC identities, lose logout
state, or break trusted module resolution.

## Install and rollback
Fresh installs create `PADIEM Connector.lnk` and package both
`claw_connect` and `padiem_connector`. If the legacy link exists, remove it
ONLY when its working directory and command identify the installed legacy
program; an unrecognized link must remain untouched. The installer continues
to require credential validation before HKCU autostart registration.

Keep older CLI aliases and Resident imports operational throughout the
transition. Switch the Resident launch from `kagent` only after separately
proving the new Agent module is packaged on target PCs and runs the same
Worker session with no change in authority.

Status: SOURCE-ONLY / DRAFT / production gateway OFF / merge prohibited until
exact-head CI and reviewed Windows upgrade/downgrade verification.
