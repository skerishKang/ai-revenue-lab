# Motion Spec — Context-to-Safer-Route Brief

- Host: `[data-route-trace]`
- Replay: `[data-motion-replay]`
- State: `idle|complete → running → complete`
- Sequence: context → constraints → route options → evidence → uncertainty → accessibility/fallback → human selection → check-in → seal.
- Completion authority: `.route-brief-seal` actual `animationend` where `animationName === routeBriefComplete`.
- Fixed timeout: prohibited and absent.
- Nominal end: 640ms delay + 140ms duration = 780ms.
- Replay removes previous running/complete classes and forces style recalculation.
- Reduced motion immediately exposes the information-complete state.
- Missing evidence, uncertainty, accessibility and non-guarantee remain visible after completion.
