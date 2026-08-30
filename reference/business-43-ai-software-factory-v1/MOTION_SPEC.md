# Motion specification

## Signature

`Requirement-to-Verified-Delivery-Package / 요구사항에서 사람 검증 전달 패키지로`

## Sequence

1. requirement
2. acceptance criteria
3. bounded patch plan
4. changed files
5. implementation self-check
6. test evidence
7. independent validation
8. Draft PR package
9. release constraints
10. `HUMAN-VERIFIED SOFTWARE DELIVERY PACKAGE`

## Contract

- Replay control: `[data-motion-replay]`
- Motion host: `[data-delivery-line]`
- State: `idle|complete → running → complete`
- Final authority: `.software-delivery-seal` actual `animationend`
- Required animation name: `deliveryPackageComplete`
- Final delay: 660ms
- Final duration: 120ms
- Nominal computed completion: 780ms
- Fixed completion timeout: prohibited
- Replay 1/2 final computed styles and geometry: equal
- Focus and scroll: stable
- Reduced motion: immediate information-complete state
- Persistent after completion: `FAILED CHECK`, `UNRESOLVED CONDITION`, `NOT MERGED`, `DEPLOYMENT READINESS — NOT DEPLOYED`, `HUMAN REVIEW REQUIRED`
