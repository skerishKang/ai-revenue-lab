# Padiem Chat — React clone (B62 / #5298)

An independent **React + Vite + TypeScript** clone of the Padiem Chat · Claw
first screen. It exists so the representative can compare the React
reconstruction against the running product and against the HTML/CSS/JS
reconstruction in [#5299](https://github.com/skerishKang/ai-revenue-lab/issues/5299).

The operational product in `apps/padiem-chat/` is **never modified**. This app
only reads from it.

## What this is (and is not)

| | |
|---|---|
| Rendered | The operational first screen: sidebar, top bar, conversation panel, composer, theme, responsive layout |
| Reused read-only | The operational stylesheets, the canonical shared composer core, the attachment capability contract |
| **Not** connected | No account, no backend, no live model call, no Drive/GitHub/PC connection |
| Answers | Local **fixtures**. Every answer is marked `fixture 응답` in the conversation and the top bar carries a `복제본 미리보기` badge |

A fixture answer must never be readable as a live product answer. That is why
the disclosure sits on the answer itself and not only in this README.

## Reuse contract

| Source | Used for |
|---|---|
| `apps/padiem-chat/static/*.css` (45 sheets, operational cascade order) | The complete visual system: tokens, glass theme, portrait layer, composer, sidebar |
| `packages/padiem-conversation-ui/composer-core.js` | IME composition guard, Enter-to-send rule, textarea growth |
| `apps/padiem-chat/static/attachment-capabilities.js` | Accepted attachment formats, size limits, the Korean composer note |

`src/styles/operational.css` reproduces the operational cascade order exactly,
including the two glass sheets the operational theme bootstrap prepends and the
two it appends last. The order is load-bearing: `padiem-glass.css` and
`sidebar-utility.css` both set the sidebar brand row, and the later sheet wins.

The clone therefore follows the operational stylesheets instead of copying
them. A pinned snapshot is a separate decision and is not taken here.

## Commands

```bash
cd apps/padiem-chat-react
npm ci
npm run dev        # http://127.0.0.1:5174
npm run typecheck  # tsc --noEmit
npm run test       # vitest (component + contract)
npm run build      # tsc --noEmit && vite build
npm run preview    # serve the production build
npm run test:e2e   # playwright (desktop + mobile chromium)
```

## First-screen parity

Measured against the operational `apps/padiem-chat/static/` build at
1440×900 and 412×915, in the `padiem-glass`, `light` and `dark` themes — 18
element positions per combination, 108 in total.

```text
102 / 108 elements match within 2px (x) / 2px (width) / 8px (height)
  6 / 108 differ: #historySection in every combination
```

The six differences are one intentional difference: the operational product
hides the recent-conversation section until the server reports a signed-in
owner's history, while the clone renders its local fixture conversations. The
issue asks for the recent-conversation list on the first screen, so the clone
shows it.

## Known differences from the operational product

- **Recent conversations** are fixtures, not server conversations.
- **The model pill** shows a generic execution contract, not a provider model.
  The public repository does not publish model-to-tier assignments.
- **Voice input** is inert. The buttons are rendered with the operational
  markup and stay disabled until a server-granted recognizer and a signed-in
  session exist, exactly like the operational product before login.
- **The Claw destination cards** report `연결 확인 필요` and never claim a
  connection the clone cannot prove.
- **Claw tool execution** is not part of this PR. It needs the Connector and
  PC execution contracts, which this PR does not touch.

## Structure

```text
src/
  App.tsx                 shell state, fixture source, theme binding
  components/             Sidebar, TopBar, ConversationView, Composer, ...
  data/                   fixture conversations, models, connectors
  state/chatStore.ts      reducer; no transport in it
  theme/theme.ts          data-theme contract (light/dark/cinematic/home/glass)
  lib/                    typed access to the reused operational modules
  styles/operational.css  the operational stylesheet import list
  styles/clone.css        clone-only layer (popovers, fixture badge)
e2e/first-screen.spec.ts  browser verification
```

## Scope

This is PR 1 of the #5298 series:

1. **This PR** — app bootstrap, first screen, theme, responsive layout, tests.
2. Chat features against the existing B62/B14 API.
3. Claw features against the existing Connector and PC execution contracts.
4. Library, automation, calendar, meeting notes, settings, i18n, accessibility.
