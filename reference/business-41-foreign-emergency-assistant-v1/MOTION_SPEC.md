# Motion specification

## Signature motion

**Language-to-Emergency-Reporting-Brief / 언어 선택에서 사람 준비형 긴급신고 브리프로**

## Sequence

1. preferred language
2. communication need
3. user statement
4. observable facts and unknowns
5. location description and uncertainty
6. critical facts
7. immediate need and accessibility support
8. official-service handoff boundary
9. `HUMAN-READY EMERGENCY REPORTING BRIEF`

## Deterministic contract

- Replay control: `[data-motion-replay]`
- Motion board: `[data-report-trace]`
- Completion authority: actual `animationend` on `[data-final-motion-element]`
- Completion animation name: `briefComplete`
- Final delay: `650ms`
- Final duration: `120ms`
- Nominal completion: `770ms`
- Fixed completion timeout: prohibited and not used
- Animation affects only opacity, transform and final shadow; layout geometry is reserved before replay
- Completion keeps the following visible: unknown information, partial location, not-live/not-verified location, no-live-connection disclosure and official handoff requirement
- Replay preserves focused element and scroll position
- Replay 1 and Replay 2 must end with equal computed styles and geometry

## Reduced motion

When `prefers-reduced-motion: reduce` is active, the replay function immediately marks the board information-complete with `data-completion-authority="reduced-motion"`. No information is hidden or delayed.
