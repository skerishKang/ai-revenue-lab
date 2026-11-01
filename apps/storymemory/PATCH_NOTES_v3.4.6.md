# StoryMemory v3.4.6 — SM-089 On-Demand Auto Pack Generation + Precision Escalation

- Adds `storymemory-auto-pack-generation-1.0` as a separate layer above the unchanged Universal Source, Trust, Pack Runtime, Marketplace, and Source UI contracts.
- Adds a **PRECISION · 정확도 높이기** action inside the existing RIGHT AI Companion. Quick/Auto is the default; Deep requires an explicit user choice.
- Precision escalation is demand-driven. Explicit user request, repeated corrections, retrieval failure, same-name collision, citation insufficiency, or Strict/high-accuracy need may trigger Pack generation; normal successful Source conversation does not.
- Generation sends only bounded Source evidence to a replaceable generator-provider hook and records `fullSourceSent=false`.
- Generated Pack default is `PRIVATE + AUTO-GENERATED + UNVERIFIED`. It is never automatically published.
- A concrete failed question is measured before and after attach. If there is no measurable retrieval improvement, the generated Pack is automatically detached and not retained.
- Confirmed user corrections can produce a safe Search Pack without an external generator provider.
- Source-body fields are rejected from provider proposals. Hard Trust / spoiler / workbook reveal rules remain non-overridable.
- Deep Pack knowledge is accepted only when its evidence locator belongs to the bounded Source evidence supplied for that generation request.
- Optional Neon draft persistence stores registry/version metadata only and requires a durable external Pack artifact URI; Pack payload and Source body are not stored in Neon by SM-089.
- Existing public Marketplace state and Odyssey Gold knowledge are read-only and unchanged.
- Cloudflare / BI Portal / DNS deployment remains deferred to `/b61/`.
