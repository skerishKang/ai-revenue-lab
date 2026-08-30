# Independent Local Validation

Validation authority is separate from the implementation self-check. The validator runs the finalized source from a fresh exact-head source snapshot under localhost Chromium and records machine-readable output in `local-validation.json`.

## Required matrix

- viewports: `1440×1100`, `768×1024`, `390×844`
- states: `cover`, `package`, `workflow`, `compatibility`, `evidence`, `listing`, `mobile`
- combinations: `21/21`

## Result

- overflow / clipping / overlap: `0 / 0 / 0`
- tab / panel contract: `7 / 7`
- keyboard navigation and visible focus: `PASS`
- local asset HTTP / decode / render: `PASS`
- console / page / failed / external requests: `0 / 0 / 0 / 0`
- authority labels and forbidden-implication checks: `PASS`
- signature motion: actual final-element `animationend`, final actual last
- observed replay timing: both runs within `700–800ms`
- moving children after completion: `0`
- Replay 1/2 final style, geometry and screenshot equality: `PASS`
- focus / scroll stability: `PASS`
- reduced motion immediate complete: `PASS`
- dedicated `390px` listing brief readability: `PASS`
- source integrity and scope: `PASS`

The exact validated Git SHA and approval disposition are recorded in the Draft PR conversation after the remote branch head is fixed. This file does not authorize Ready, merge, Issue closure, UX or backend work.
