# Technology adoption guidance

## Search / adopt before build

For substantial new capabilities, workers and the Web CTO follow the canonical technology-adoption gate before custom implementation:

```text
SEARCH
→ REUSE_INTERNAL
→ BUY / ADOPT / ADAPT
→ SIDECAR / LOCAL_SERVICE
→ BUILD_FROM_SCRATCH
```

Open-source and commercial technology are both valid. Paid APIs, SDKs, commercial licenses and self-hosted products may be preferable to weeks of custom development.

A custom commodity implementation requires an explicit reason. Historical `SECOND_*` locks mean no competing **Padiem product authority**; they do not prohibit internal parsers/decoders/native libraries used behind one reviewed adopted-project boundary.

See `docs/operations/TECHNOLOGY_ADOPTION_POLICY.md`.

Technology discovery does not automatically pause an already-approved active task. Continue the bounded accepted scope while scans run in parallel; use new findings for the next slice or a reviewed replacement decision unless CENTRAL explicitly pauses the work.
