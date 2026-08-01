# Motion specification

## Signature

`Source-to-Public-Data-Connector-Spec / 공공 원천에서 사람 검토 커넥터 명세로`

## Sequence

1. source catalog
2. authority and licence
3. access method
4. raw schema
5. normalized mapping and field lineage
6. freshness and validation
7. limitations and readiness boundary
8. `HUMAN-REVIEWED PUBLIC DATA CONNECTOR SPEC`

## Contract

- Replay control: `[data-motion-replay]`
- Motion host: `[data-connector-line]`
- State: `idle|complete → running → complete`
- Final authority: `.connector-spec-seal` actual `animationend`
- Required animation name: `connectorSpecComplete`
- Final delay: 660ms
- Final duration: 120ms
- Nominal computed completion: 780ms
- Fixed completion timeout: prohibited
- Replay 1/2 final styles, screenshots and geometry: equal
- Focus and scroll: stable
- Reduced motion: immediate information-complete state
- Persistent after completion: licence limitation, stale/unknown, `MISSING ≠ ZERO`, incomplete coverage, no endorsement and not-connected boundary
