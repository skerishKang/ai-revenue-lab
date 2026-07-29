# Motion specification

## Signature

`Submission-to-Verification-Record / 제출물에서 사람 승인 검증기록으로`

## Sequence

1. exact submission;
2. worker claims;
3. acceptance criteria;
4. independent checks;
5. evidence and exact-version match;
6. exception;
7. residual condition;
8. validator verdict;
9. separate human approval;
10. `HUMAN-APPROVED VERIFICATION RECORD`.

## Completion authority

The final `.approval-record` runs animation `briefComplete`. Its actual `animationend` event is the only completion authority. Application JavaScript contains no `setTimeout` completion fallback.

Computed nominal completion:

- delay: 660ms;
- duration: 110ms;
- total: 770ms.

## Replay invariants

- deterministic DOM/class reset;
- Replay 1 and Replay 2 final computed styles equal;
- Replay 1 and Replay 2 final screenshot bytes equal;
- Replay 1 and Replay 2 final geometry equal;
- replay-button focus stable;
- scroll position stable;
- verification-board geometry stable;
- reduced motion immediately reaches information-complete state.

## Persistent information

Failed/skipped/unavailable distinctions, stale evidence, residual condition, limited approval scope, no universal certification and deployment-not-authorized remain visible after completion.
