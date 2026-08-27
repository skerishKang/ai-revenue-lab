# Source-to-Research-Memory Trace

Sequence: research question → source fragment → researcher annotation → equation context → claim/evidence → reviewer objection → revision/unresolved question → `HUMAN-REVIEWED RESEARCH MEMORY`.

- Replay: `[data-motion-replay]`
- Host: `[data-memory-trace]`
- State: `idle|complete → running → complete`
- Final authority: `.memory-seal` `animationend`, animation `memoryComplete`
- No fixed timeout
- Nominal end: 640ms + 140ms = 780ms
- Reduced motion: immediate complete
- Contradiction, objection and unresolved question remain visible.
