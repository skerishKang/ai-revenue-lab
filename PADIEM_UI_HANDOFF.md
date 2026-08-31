# Padiem Chat UI handoff

This is an isolated, detached worktree for the Padiem Chat UI redesign.

Changed frontend files:
- `apps/padiem-chat/static/index.html`
- `apps/padiem-chat/static/app.js`
- `apps/padiem-chat/static/locale.js`
- `apps/padiem-chat/static/padiem-themes.css`
- `apps/padiem-chat/static/theme-init.js`
- `apps/padiem-chat/static/theme.js`

Current UI direction:
- Default theme: `Padiem Home`
- Theme order: `Padiem Home`, `Light`, `Dark`, `Cinematic`
- Theme and language controls are inside `설정 / Settings`
- Language buttons: `KR / EN`
- Sidebar link: `Padiem Home` → `https://padiem.net/`

Validation already completed:
- Frontend contract tests: 36 passed
- Full suite: 319 passed; 1 environment-only failure because `workers-runtime-sdk` metadata is unavailable
- JavaScript, HTML, CSS checks passed
- Local mock runtime smoke test passed

No deployment was performed.
