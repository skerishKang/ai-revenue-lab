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
| Reused read-only | The operational stylesheets, the canonical shared composer core, the attachment capability contract, the chat transport |
| **Answers** | The real Chat API when one is reachable. Local **fixtures** only when it is not, and the top bar says which one is in use |
| **Not** connected | No Drive/GitHub/PC connection, no Claw tool execution (the next slices of the series) |

A fixture answer must never be readable as a live product answer. The top bar
badge states the source at all times (`실제 API 연결`, `API 확인 중`,
`복제본 미리보기`), and a fixture answer additionally carries a `fixture 응답`
label next to the answer itself.

## Connecting a Chat API

The clone speaks the operational Chat contract: the same `/api/chat/stream`
transport, the same conversation routes and the same session cookie. The dev
server proxies `/api` to the API origin, so the browser stays same-origin and
the reviewed same-origin guard keeps working.

```bash
# Windows PowerShell
$env:PADIEM_CHAT_API_BASE_URL = "https://chat.padiem.net"
npm run dev
```

There is **no default API base URL** on purpose. Without it the clone stays in
its offline fixture mode and never reaches a live API from a developer machine
by accident. Point it at a local or mock deployment while developing; a live
deployment spends real provider quota.

The proxy sends the API origin as the `Origin` header, because the operational
same-origin guard compares the request origin with the server's own
`public_base_url` and never with the request host. The session cookie is
rewritten to the dev origin, so a password login through the proxy keeps the
session.

A browser-originated request to the deployed Chat API needs a signed-in
session: the API answers an `Origin`-carrying request without a session with
`401`. The clone therefore signs in through the operational password route
(`POST /api/auth/password/login`) and the operational `padiem_session` cookie
decides the rest. The clone has no authentication of its own and never creates
an account by itself.

The account tier is deliberately not sent. The server owns the account's tier,
and the clone has no tier authority to claim one. The model control shows a
generic execution contract, and the public repository does not publish
model-to-tier assignments.

## Reuse contract

| Source | Used for |
|---|---|
| `apps/padiem-chat/static/*.css` (46 sheets, operational cascade order) | The complete visual system: tokens, glass theme, portrait layer, composer, sidebar |
| `packages/padiem-conversation-ui/composer-core.js` | IME composition guard, Enter-to-send rule, textarea growth |
| `apps/padiem-chat/static/attachment-capabilities.js` | Accepted attachment formats, size limits, the Korean composer note |
| `apps/padiem-chat/static/chat-transport.js` | The Chat request contract: `/api/chat/stream`, `/api/chat`, the orchestration readiness check and the SSE frame reader |
| `apps/padiem-chat/static/padiem-glass-shell.js` | The glass portrait and its twenty registered shell ribbons |

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

- **The B66 Padiem Quote launcher** appears in the operational Chat sidebar.
  That entry belongs to an independent product, the clone has no quote surface
  to open, and a dead entry would be a control that does not work, so it stays
  out of this PR and is recorded instead.
- **The model pill** shows a generic execution contract, not a provider model.
  The public repository does not publish model-to-tier assignments.
- **Voice input** is inert. The buttons are rendered with the operational
  markup and stay disabled until a server-granted recognizer and a signed-in
  session exist, exactly like the operational product before login.
- **The Claw destination cards** report `연결 확인 필요` and never claim a
  connection the clone cannot prove.
- **Claw tool execution** is not part of this PR. It needs the Connector and
  PC execution contracts, which this PR does not touch.
- **The recent-conversation list** comes from the API when one is reachable and
  from local fixtures otherwise. The operational product hides the section
  until the server reports a signed-in owner's history.

## Structure

```text
src/
  App.tsx                 shell state, the API probe, the answer source
  api/                    the real Chat API client and its response shapes
  components/             Sidebar, TopBar, ConversationView, Composer, ...
  data/                   fixture conversations, models, connectors
  state/chatStore.ts      reducer; no transport in it
  theme/theme.ts          data-theme contract (light/dark/cinematic/home/glass)
  lib/                    typed access to the reused operational modules
  styles/operational.css  the operational stylesheet import list
  styles/clone.css        clone-only layer (popovers, source badge)
e2e/first-screen.spec.ts  browser verification
```

## Scope

This is the second slice of the #5298 series:

1. **PR #5465** — app bootstrap, first screen, theme, responsive layout, tests.
2. **This PR** — the real Chat API: conversation list, conversation detail,
   conversation delete, the streaming answer and the session cookie.
3. Claw tool execution and approval flow (the Connector and PC contracts).
4. Library, automation, calendar, meeting notes, settings, i18n, accessibility.
