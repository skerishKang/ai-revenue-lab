# Motion specification

## Signature

`Capability-to-Embedded-Integration-Spec / 기능에서 사람 승인 임베드 통합 명세로`

## Sequence

1. host product
2. insertion point
3. input/output contract
4. data and permission boundary
5. compatibility
6. fail-closed fallback
7. human release review
8. `HUMAN-APPROVED EMBEDDED AI INTEGRATION SPEC`

## Contract

- Replay control: `[data-motion-replay]`
- Motion host: `[data-integration-line]`
- State: `idle|complete → running → complete`
- Final authority: `.integration-spec-seal` actual `animationend`
- Required animation name: `integrationSpecComplete`
- Final delay: 650ms
- Final duration: 110ms
- Nominal computed completion: 760ms
- Fixed completion timeout: prohibited
- Final seal is the actual last animation
- Replay 1/2 final computed style, screenshot and geometry: deterministic equality target
- Focus, scroll and geometry: stable target
- Reduced motion: immediate information-complete state
- Persistent after completion: permission not granted, installation not performed, execution not performed and model/provider not connected
