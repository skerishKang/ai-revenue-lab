# B49 — Public Data Connector Hub Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh platform audit: run `31422928265`, artifact `9076118820`, canonical `https://49-public-data-connector-hub.pages.dev/`. Current generic card prototype does not make source/schema/mapping the visual product.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

Public data sources become a bounded connector contract only after schema is inspected, fields are mapped and validation exposes missing/incompatible data.

```text
DATA SOURCES → SCHEMA → FIELD MAPPING → VALIDATION → CONNECTOR CONTRACT
```

Core object: **the schema/field mapping map**.

## Reserved territory — Schema Connector Blueprint

- source endpoints/files as left-side contracts
- schema fields and types visible
- mapping lines between source and target fields
- validation errors attached to exact mapping
- final connector contract readable as inputs/outputs/limits

Avoid generic cards, node spaghetti, public-data portal map, API marketing page and B53 SDK insertion frame.

## Acceptance criteria

1. schemas/fields are the main visible objects;
2. mappings are spatially explicit;
3. validation attaches to exact fields;
4. final connector contract preserves source/target boundaries;
5. generic B45–B49 shell is gone;
6. Mobile uses grouped field mappings without losing correspondence;
7. no live external data/backend behavior is added by visual work.
