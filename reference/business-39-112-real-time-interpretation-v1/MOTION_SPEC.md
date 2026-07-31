# Motion Spec — Caller-to-Verified-Relay Trace

- Host: `[data-call-trace]`
- Replay: `[data-motion-replay]`
- State: `idle|complete → running → complete`
- Sequence: caller speech → transcript → interpretation → critical terms → clarification → correction → bilingual summary → unresolved meaning → seal.
- Completion authority: `.call-record-seal` actual `animationend` where `animationName === callRecordComplete`.
- Fixed timeout: absent.
- Nominal completion: 640ms delay + 140ms duration = 780ms.
- Replay resets previous completion and forces style recalculation.
- Reduced motion immediately exposes the same information-complete state.
- Transcript uncertainty, critical terms, unresolved meaning and no-dispatch boundary remain visible.
