# Padiem Claw Ops — Communication Connector Contract

Status: Draft implementation contract

## Purpose

Define the product-owned message transport boundary for Claw Ops without granting the product raw credential authority or permission to scrape personal messenger sessions.

## Channels

- email
- SMS
- business messaging
- Kakao Business API surface

Personal Kakao/session scraping is explicitly unsupported.

## Outbound rule

Every outbound request is bound to:

- workspace
- business target kind/id/version
- action fingerprint
- approval ID
- recipient reference
- bounded subject/body
- validated attachments

The connector is injected. The default implementation fails closed and performs no network activity.

## Inbound rule

Incoming message bodies and attachments are always untrusted input. They may be parsed into business records only through a separate intake/validation workflow. Message text itself cannot become execution authority.

## Attachment policy

Initial allowlist:

- PDF
- XLS/XLSX
- CSV
- TXT
- DOCX

Executables and unknown MIME types are rejected. File count and file size are bounded and content hashes are required.

## Audit projection

General audit projections omit raw body/subject content and expose only bounded metadata such as message ID, target version, attachment IDs, body hash and body length.

## Credential boundary

Only opaque credential references may cross into product configuration. Raw Provider or connector secret values are not accepted by this contract.

## Authority

- B54 owns business message intent and connector adapter.
- P01 owns generic approval/tool/evidence semantics.
- Control Plane/B14 or a trusted connector-secret store own actual secret values and authorization.

## Non-goals

- no real email send in this slice
- no Kakao account mutation
- no personal messenger scraping
- no autonomous commercial commitment
- no inbound message auto-execution
- no Production deployment
