# Motion specification

## Signature

`Host-Surface-to-Approved-Embed-Contract / 호스트 화면에서 사람 승인 임베드 계약으로`

## Sequence

1. host product identity
2. proposed mount point
3. approved capability cartridge
4. explicit context envelope
5. event and callback contract
6. permission and human action gate
7. compatibility, fail-closed and fallback
8. `HUMAN-APPROVED EMBEDDED AI INTEGRATION CONTRACT`

## Contract

- Replay control: `[data-motion-replay]`
- Motion host: `[data-embed-trace]`
- State: `idle|complete → running → complete`
- Final authority: `.integration-contract-binder` actual `animationend`
- Required animation name: `embedContractComplete`
- Final delay: 660ms
- Final duration: 120ms
- Nominal completion: 780ms
- Fixed completion timeout: prohibited
- Replay 1/2 final style, screenshot and geometry equality required
- Focus, scroll and geometry remain stable
- Reduced motion becomes immediately information-complete

## Persistent boundaries

The following remain visible outside the animated trace:

- `HOST PRODUCT — UNCHANGED`
- `NO DOM SCRAPING`
- `PERMISSION REQUEST — NOT GRANTED`
- `HOST ACTION — HUMAN CONFIRMATION REQUIRED`
- `MODEL / PROVIDER — NOT SELECTED`
- `FAIL CLOSED`
- `FALLBACK TO HOST UI`
- `INSTALLATION READINESS — NOT INSTALLED`
- `NO LIVE API, MODEL CALL, CREDENTIAL, STORAGE, TELEMETRY, OR HOST MUTATION`
