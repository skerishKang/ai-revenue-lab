# B14 Provider Intake Registry

This directory records approved or candidate upstream provider integrations without secret values.

Rules:

- Provider credentials are never committed.
- Each provider intake must declare fixed upstream origin, model IDs, credential binding name, capabilities, free/paid evidence state, and public/shared-use disposition.
- `b14/auto` and explicit model selection remain separate supported client behaviors.
- A provider may be code-integrated for owner/local smoke while remaining excluded from the public shared-free pool.

Current entries:

- `AGNES_AI_V1.md` — candidate; owner/local smoke allowed; public shared-free pool on hold pending terms confirmation.
