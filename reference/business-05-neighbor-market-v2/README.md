# Business 5 · 우리단지 이웃가게 v3 Reference

Issue: #89  
Branch: `design/business-05-neighbor-market-v2-89`  
Reference path: `reference/business-05-neighbor-market-v2/**`

## Status

This is a controlled **reference design**, not an implementation branch and not a production service.

The purpose is to freeze product direction, content hierarchy, visual quality and interaction behavior before a local coding model is allowed to create `apps/neighbor-market/**`.

Do not merge this reference branch into `main` until the visual direction is explicitly approved.

## Product

- Business number proposal: **5**
- Korean product name: **우리단지 이웃가게**
- English name: **Neighbor Market**
- Stable slug: `neighbor-market`
- Reference apartment: **방림명지로드힐**
- Public road address: **광주광역시 남구 대남대로85번길 3**
- Proposed future workspace: `apps/neighbor-market/**`

The public apartment facts used in the prototype are limited to name, address, 192 households, 2 buildings and 2015-10-30 use approval. No resident name, building/unit number, roster or identity evidence is included.

## Current primary prototype

Use **`index-v3.html`**.

The earlier `index.html` remains only as a comparison artifact and is not the current visual target.

V3 applies the frozen consumer-marketplace finish rules:

- reduced card radius and shadow;
- refined Korean typography scale;
- production-style search and select controls;
- photographic business cards;
- mobile vertical shop list;
- price, availability and benefit hierarchy;
- business-specific order, reservation, quote and consultation actions;
- mobile bottom navigation;
- shop-detail sticky mobile actions;
- dedicated benefits, owner registration, favorites/my and QA states.

## Open the prototype

### Safe local worktree launcher

Run `LOCAL_PREVIEW.ps1` from PowerShell. The script:

- fetches the exact remote reference branch;
- leaves the user's existing checkout untouched;
- creates or refreshes a dedicated detached worktree;
- refuses to reset or clean a dirty target;
- starts a local static server;
- opens `index-v3.html` in the default browser.

Default paths:

```powershell
powershell -ExecutionPolicy Bypass -File .\LOCAL_PREVIEW.ps1
```

Override paths when required:

```powershell
powershell -ExecutionPolicy Bypass -File .\LOCAL_PREVIEW.ps1 `
  -RepoPath "G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab" `
  -WorktreePath "G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-neighbor-market-reference" `
  -Port 4173
```

### Manual opening

Serve the directory:

```bash
python -m http.server 4173 --bind 127.0.0.1
```

Then open:

```text
http://127.0.0.1:4173/index-v3.html
```

Navigation uses URL hashes:

- `#home`
- `#explore`
- `#detail`
- `#benefits`
- `#register`
- `#my`
- `#qa`

## Safety and honesty

- All shop names, prices, benefits, opening states and service descriptions are synthetic.
- No order, contact, login or registration data is transmitted.
- Temporary Unsplash images are visual placeholders for reference review.
- The apartment hero image is not a photograph of 방림명지로드힐; it is explicitly marked as a reference image.
- Before production, the apartment photo must be replaced with a user-supplied or permission-cleared real photo.
- The current representative-chair name is intentionally not displayed.

## Files

- `index-v3.html` — current primary clickable product reference
- `index.html` — superseded v2 comparison artifact
- `DESIGN_SPEC.md` — product, visual and interaction decisions
- `UI_REFINEMENT_V3.md` — fixed consumer-marketplace finish rules
- `IMAGE_SOURCES.md` — temporary image and font source ledger
- `LOCAL_HANDOFF_PROMPT.md` — strict future local-worker implementation prompt
- `LOCAL_PREVIEW.ps1` — safe dedicated-worktree V3 preview launcher
- `SCREENSHOT_MATRIX.md` — required desktop, tablet, mobile and state screenshots

## Review sequence

1. Sync the exact reference branch into a clean dedicated worktree.
2. Open `index-v3.html` through the local server.
3. Capture every required screenshot in `SCREENSHOT_MATRIX.md` without source changes.
4. Review the prototype visually on desktop and mobile.
5. Revise only the reference branch until approved.
6. Create a separate documentation change for Business 5 registry assignment.
7. Create a separate implementation branch under `apps/neighbor-market/**`.
8. Give the local worker the strict handoff prompt and approved reference commit SHA.
9. Keep the implementation PR Draft until screenshot comparison passes.
