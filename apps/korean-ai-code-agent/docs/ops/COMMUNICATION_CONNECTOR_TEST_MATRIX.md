# Claw Ops Communication Connector Test Matrix

| Area | Required behavior |
|---|---|
| Default connector | Fail closed / zero network |
| Approval binding | Exact approval ID + object version + action fingerprint |
| Recipient | Reference only; secret-like values rejected |
| Attachments | Allowlist + size/count bounds + SHA-256 |
| Inbound trust | Always untrusted execution input |
| Audit | No raw body/subject in general log projection |
| Personal messenger | Scraping/session automation unsupported |
| Kakao | Business API surface only |
| Credential | Opaque secret reference only |
| Test adapter | Deterministic and network-free |
