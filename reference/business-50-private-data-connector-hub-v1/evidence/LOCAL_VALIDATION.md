# Independent Local Validation

- Validated source head: `373776bd1a4f43eee92f7b5cbfafae4cdb6492fe`
- Validation mode: fresh detached git worktree, localhost HTTP, headless Chromium
- Status: **PASS**

## Results

- viewport/state matrix: `21/21 PASS`
- tab/panel reciprocal AT mapping: `7/7 PASS`
- keyboard Arrow/Home/End controls: `PASS`
- local assets HTTP/decode/render: `12/12 PASS`
- scope and authority boundaries: `PASS`
- secret/token value exposure: `0`
- prohibited implication: `0`
- signature motion actual final: `779ms`, `781ms`
- final authority: final node actual `animationend`
- fixed completion timeout: `none`
- Replay computed style and geometry equality: `PASS`
- focus/scroll stability: `PASS`
- completed animation count: `0`
- reduced motion immediate completion: `PASS`
- 390px containment: `PASS`
- console/page/failed/external network: `0/0/0/0`
- source-head visual inspection: `PASS`

The source-only head failed once for an absent evidence output directory and once for a 1px rotated-stamp overflow. Both failures were patched in new commits and this report records only the fresh exact-head rerun.
