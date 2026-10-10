# B62 Glass animation certification policy — #3989

Status: PR #4247 implementation, reviewed 2026-10-11 KST.

## PR-required visual-functional contract

The B62 Unified Browser QA workflow continues to require the live Chromium
desktop/mobile/Claw tablet checks, authenticated/session and owner-feature
browser lanes, screen/interaction/certification evidence, and the 3-suite
Glass visual tail whenever the fail-closed impact planner selects it.

The Glass shell variant suite **still runs in PRs** in
`B62_GLASS_SHELL_MODE=functional` and must pass for both female and male
variants: portrait image and 20 shell fragments, idle assembled shell,
pointer hover reaching a clean peeled portrait, restoration after pointer
exit, answer-only nonpeel, combined answer/pointer peel, mask controls,
reduced-motion/touch, horizontal overflow, and screenshot artifacts.
The original `b62_browser_qa_tail_parallel.py` 3-suite failure fan-in,
Glass zoom and gutter suites remain intact and blocking. Unknown/mixed
changes still select these checks; proven leaf-only changes retain their
previously approved optimized lane selection.

## Independent STRICT frame-timing certification

`.github/workflows/b62-glass-animation-timing-certification.yml` triggers
automatically **every day at 18:25 UTC / 03:25 KST the following day**, on
GitHub default `main`. It runs in `PADIEM_CHAT_RUNTIME_MODE=mock`,
`B62_GLASS_SHELL_MODE=strict`, uses the pinned Playwright browser, and runs
the original `b62_glass_shell_visual_qa.py` timing source without altered
thresholds (peel 1800–3600ms; recovery 1600–3600ms; 260/900ms sampling
and original timing retries). Failing the strict check MUST fail the
scheduled job and retain the `glass-shell-report.json` evidence for 30 days.

The scheduled certification is intentionally **not a required PR status
check**. A daily timing failure is not a PASS and must be investigated using
recorded page-clock overshoot/FPS diagnostics. It must not automatically
weaken the original contracts, silently retry the entire workflow, change
Production Secrets, or make live provider calls. Production or release
gate changes require an independent decision.

## Separation and safety

The `B62_GLASS_SHELL_MODE` default remains `strict` for direct and
scheduled invocations. The PR workflow explicitly opts into
`functional` for its one Glass-tail step; no global environment variable
or production service behavior changes. An unknown mode is rejected.

This separation addresses two observed full-PR failures in #4247:
`glass-shell-female` 3755ms at 8.1FPS and `glass-shell-male` 3637ms
at 9.3FPS (both above the unchanged 3600ms ceiling). It does not claim
these failures are product defects or change the strict limits.
