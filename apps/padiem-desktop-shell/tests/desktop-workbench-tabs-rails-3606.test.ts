/**
 * #3606 — renderer tests for the workbench interaction layer.
 *
 * Covers the second Desktop UI slice on top of #3604: the canonical
 * task/session tab strip, the collapsible left/right rails, the bounded
 * UI-only keyboard shortcuts, the denser presentation and the session-oriented
 * left rail — plus the truthfulness and authority guarantees that must survive
 * the polish (no fake task tab, no fake session state, no new IPC, no
 * model/provider selector, unsupported controls still non-executable).
 *
 * Everything is rendered to static markup through the real modules, so the
 * assertions see the DOM a user would see (minus hydration).
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  INITIAL_SHELL_VIEW_STATE,
  SessionListPanel,
  ShellView,
  TaskTabStrip,
  WORKBENCH_NAV_SECTIONS,
  WORKBENCH_RAIL_IDS,
  WORKBENCH_SHORTCUTS,
  WORKBENCH_UNSUPPORTED_SECTIONS,
  WorkbenchRailToggle,
  formatSessionStamp,
  resolveWorkbenchShortcut,
  type ShellActions,
  type ShellViewState,
} from '../src/renderer/app.js';
import type {
  BoundedLogResponse,
  CanonicalConversationListResponse,
  CanonicalRunListResponse,
  RunnerHealthResponse,
  ShellStatus,
  WorkspaceListResponse,
  WorkspaceRootResponse,
} from '../src/renderer/types.js';

const packageRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const rendererDir = path.join(packageRoot, 'src', 'renderer');

const NOOP_ACTIONS: ShellActions = {
  refresh: async () => undefined,
  start: async () => undefined,
  stop: async () => undefined,
  submitPairingDeepLink: async () => undefined,
  chooseWorkspaceRoot: async () => undefined,
  openWorkspaceDirectory: async () => undefined,
  clearWorkspaceRoot: async () => undefined,
  searchWorkspace: async () => undefined,
  selectWorkspaceEntry: () => undefined,
  selectConversation: async () => undefined,
};

const ROOT: WorkspaceRootResponse = {
  selected: true,
  rootName: 'customer-project',
  rootPath: 'C:\\Users\\person\\customer-project',
  reason: 'current',
};

const LISTING: WorkspaceListResponse = {
  ok: true,
  root: ROOT,
  directory: '',
  entries: [
    { name: 'src', relativePath: 'src', kind: 'directory', sizeBytes: null, modifiedAt: null },
  ],
  truncated: false,
  maxEntries: 200,
  errorCode: null,
};

const STATUS: ShellStatus = {
  deviceState: 'ONLINE',
  deviceStateRevision: 7,
  runnerState: 'RUNNING',
  runnerPid: 4242,
  pairingSeamAccepted: true,
  authoritativeTruthOwner: '#3080',
  rendererMayDeclareOnline: false,
};

const HEALTH: RunnerHealthResponse = {
  state: 'RUNNING',
  pid: 4242,
  alive: true,
  checkedAtMs: 1,
  lastExitCode: 0,
  lastExitSignal: null,
};

const LOG: BoundedLogResponse = {
  lines: ['runner: started'],
  truncated: false,
  redactionApplied: true,
};

const CHAT_A = 'chat_' + 'a'.repeat(32);
const CHAT_B = 'chat_' + 'b'.repeat(32);

const CONVERSATIONS: CanonicalConversationListResponse = {
  ok: true,
  configured: true,
  errorCode: null,
  conversations: [
    { id: CHAT_A, title: '견적서 초안 — 홍길동', createdAt: '2026-10-07T01:00:00Z', updatedAt: '2026-10-07T02:05:00Z' },
    { id: CHAT_B, title: '주문서 정리 — (주)파디엠', createdAt: '2026-10-06T09:00:00Z', updatedAt: '2026-10-06T09:40:00Z' },
  ],
};

const RUN_LIST: CanonicalRunListResponse = {
  ok: true,
  configured: true,
  liveActivitySource: 'not_yet_available',
  errorCode: null,
  runs: [
    {
      runId: 'run_a2f8c1d94b7e6035fa9c2e11',
      status: 'running',
      channel: 'web',
      action: 'quote_draft',
      title: '[WEB] quote_draft: 홍길동',
      createdAt: '2026-10-07T02:00:00Z',
      updatedAt: '2026-10-07T02:03:21Z',
      resultSummary: '견적서 초안 작성을 진행합니다.',
      artifact: null,
      conversationId: CHAT_A,
      workspaceId: null,
    },
  ],
};

function render(element: ReactElement | null): string {
  return element === null ? '' : renderToStaticMarkup(element);
}

function shellMarkup(
  state: Partial<ShellViewState> = {},
  view: 'easy' | 'advanced' = 'easy',
  locale: 'ko' | 'en' = 'ko',
): string {
  return render(
    createElement(ShellView, {
      state: { ...INITIAL_SHELL_VIEW_STATE, ...state },
      preferences: { locale, theme: 'system', view },
      actions: NOOP_ACTIONS,
      settingsOpen: false,
      onToggleSettings: () => undefined,
      onLocale: () => undefined,
      onTheme: () => undefined,
      onView: () => undefined,
      onCloseSettings: () => undefined,
    }),
  );
}

const css = readFileSync(path.join(rendererDir, 'shell.css'), 'utf8');
const appSource = readFileSync(path.join(rendererDir, 'app.tsx'), 'utf8');

// ── 1. task/session tab strip ───────────────────────────────────────────────

test('#3606 the task tab strip shows only canonical conversations', () => {
  const markup = render(
    createElement(TaskTabStrip, {
      conversations: CONVERSATIONS,
      selectedConversationId: CHAT_A,
      onSelectConversation: () => undefined,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(markup, /data-tab-source="canonical"/);
  assert.match(markup, /data-tab-count="2"/);
  assert.match(markup, /role="tablist"/);
  const tabs = [...markup.matchAll(/role="tab"/g)];
  assert.equal(tabs.length, CONVERSATIONS.conversations.length);
  assert.match(markup, /견적서 초안 — 홍길동/);
  assert.match(markup, /주문서 정리 — \(주\)파디엠/);
  // Every tab id is one the server returned; nothing is minted here.
  for (const item of CONVERSATIONS.conversations) {
    assert.match(markup, new RegExp(`data-conversation-id="${item.id}"`));
  }
});

test('#3606 exactly one tab is selected and it carries tab semantics', () => {
  const markup = render(
    createElement(TaskTabStrip, {
      conversations: CONVERSATIONS,
      selectedConversationId: CHAT_B,
      onSelectConversation: () => undefined,
      locale: 'en',
      advanced: false,
    }),
  );
  const selected = [...markup.matchAll(/aria-selected="true"/g)];
  assert.equal(selected.length, 1, 'exactly one tab is selected');
  assert.match(markup, new RegExp(`data-conversation-id="${CHAT_B}"[^>]*aria-selected="true"`));
  assert.match(markup, new RegExp(`data-conversation-id="${CHAT_B}"[^>]*data-tab-active="true"`));
  // Tabs point at the panel they control.
  assert.match(markup, new RegExp(`aria-controls="${WORKBENCH_RAIL_IDS.taskPanel}"`));
  // Roving tabindex: one tabbable tab, the rest reachable with the arrow keys.
  const tabbable = [...markup.matchAll(/tabindex="0"/gi)];
  assert.equal(tabbable.length, 1);
});

test('#3606 there is no fake task tab and no renderer-minted task id', () => {
  const markup = render(
    createElement(TaskTabStrip, {
      conversations: CONVERSATIONS,
      selectedConversationId: CHAT_A,
      onSelectConversation: () => undefined,
      locale: 'en',
      advanced: false,
    }),
  );
  for (const forbidden of ['New task', 'new-task', '새 작업', '새 대화', 'Untitled task']) {
    assert.doesNotMatch(markup, new RegExp(forbidden, 'i'), forbidden);
  }
  // No tab close: closing a tab must never read as deleting a server conversation.
  for (const forbidden of ['tab-close', 'close-tab', '닫기', 'Close tab', 'Delete']) {
    assert.doesNotMatch(markup, new RegExp(forbidden, 'i'), forbidden);
  }
  // Every rendered id came from the projection.
  const ids = [...markup.matchAll(/data-conversation-id="([^"]+)"/g)].map((match) => match[1]);
  const known = new Set(CONVERSATIONS.conversations.map((item) => item.id));
  assert.ok(ids.length > 0);
  for (const id of ids) {
    assert.ok(known.has(id ?? ''), `minted or unknown id: ${String(id)}`);
  }
});

test('#3606 an unavailable or empty canonical list is a bounded empty tab strip', () => {
  const unavailable = render(
    createElement(TaskTabStrip, {
      conversations: null,
      selectedConversationId: null,
      onSelectConversation: () => undefined,
      locale: 'en',
      advanced: false,
    }),
  );
  assert.match(unavailable, /data-tab-source="canonical-required"/);
  assert.match(unavailable, /data-tab-empty="true"/);
  assert.doesNotMatch(unavailable, /role="tablist"/);
  assert.doesNotMatch(unavailable, /data-tab-count/);
  assert.doesNotMatch(unavailable, /chat_[0-9a-f]/);

  const empty = render(
    createElement(TaskTabStrip, {
      conversations: { ...CONVERSATIONS, conversations: [] },
      selectedConversationId: null,
      onSelectConversation: () => undefined,
      locale: 'en',
      advanced: false,
    }),
  );
  assert.match(empty, /data-tab-source="canonical"/);
  assert.match(empty, /data-tab-count="0"/);
  assert.match(empty, /No task tabs yet/);
});

test('#3606 the tab strip sits outside the tab panel it labels', () => {
  const markup = shellMarkup(
    { conversationList: CONVERSATIONS, selectedConversation: null },
    'easy',
    'ko',
  );
  // The tablist is rendered before the panel and is not nested in it.
  const tablistAt = markup.indexOf('role="tablist"');
  const panelAt = markup.indexOf(`id="${WORKBENCH_RAIL_IDS.taskPanel}"`);
  assert.ok(tablistAt >= 0 && panelAt > tablistAt);
  assert.match(markup, /role="tabpanel"/);
  // With nothing selected the panel falls back to the conversation heading.
  assert.match(markup, /aria-labelledby="desktop-conversation-title"/);
});

test('#3606 the active tab labels the task panel', () => {
  const markup = render(
    createElement(ShellView, {
      state: {
        ...INITIAL_SHELL_VIEW_STATE,
        conversationList: CONVERSATIONS,
        selectedConversation: {
          ...(CONVERSATIONS.conversations[1] as NonNullable<
            CanonicalConversationListResponse['conversations'][number]
          >),
          messages: [],
        },
      },
      preferences: { locale: 'ko', theme: 'system', view: 'easy' },
      actions: NOOP_ACTIONS,
      settingsOpen: false,
      onToggleSettings: () => undefined,
      onLocale: () => undefined,
      onTheme: () => undefined,
      onView: () => undefined,
      onCloseSettings: () => undefined,
    }),
  );
  assert.match(markup, /aria-labelledby="workbench-task-tab-1"/);
});

// ── 2. collapsible rails ────────────────────────────────────────────────────

test('#3606 a rail toggle is a button with a name, aria-expanded and aria-controls', () => {
  const expanded = render(
    createElement(WorkbenchRailToggle, {
      side: 'left',
      collapsed: false,
      onToggle: () => undefined,
      locale: 'en',
    }),
  );
  assert.match(expanded, /<button/);
  assert.match(expanded, /data-rail-toggle="left"/);
  assert.match(expanded, new RegExp(`aria-controls="${WORKBENCH_RAIL_IDS.left}"`));
  assert.match(expanded, /aria-expanded="true"/);
  assert.match(expanded, /aria-label="[^"]*Collapse"/);
  assert.doesNotMatch(expanded, /disabled/);

  const collapsed = render(
    createElement(WorkbenchRailToggle, {
      side: 'left',
      collapsed: true,
      onToggle: () => undefined,
      locale: 'en',
    }),
  );
  assert.match(collapsed, /aria-expanded="false"/);
  assert.match(collapsed, /aria-label="[^"]*Expand"/);

  const right = render(
    createElement(WorkbenchRailToggle, {
      side: 'right',
      collapsed: true,
      onToggle: () => undefined,
      locale: 'ko',
    }),
  );
  assert.match(right, new RegExp(`aria-controls="${WORKBENCH_RAIL_IDS.right}"`));
  assert.match(right, /aria-expanded="false"/);
  assert.match(right, /도구 레일/);
  assert.match(right, /펼치기/);
});

test('#3606 the shell renders both rail regions with the ids its toggles control', () => {
  const markup = shellMarkup({ status: STATUS, health: HEALTH }, 'easy', 'ko');
  assert.match(markup, /data-left-rail="expanded"/);
  assert.match(markup, /data-right-rail="expanded"/);
  assert.match(markup, new RegExp(`id="${WORKBENCH_RAIL_IDS.left}"`));
  assert.match(markup, new RegExp(`id="${WORKBENCH_RAIL_IDS.right}"`));
  assert.match(markup, /data-rail="left"/);
  assert.match(markup, /data-rail="right"/);
  assert.match(markup, /data-rail-state="expanded"/);
  // The two toggles are present in the always-visible top bar.
  assert.match(markup, /data-rail-toggle="left"/);
  assert.match(markup, /data-rail-toggle="right"/);
});

test('#3606 collapsing a rail is layout only: the centre column keeps the free space', () => {
  // The rails are sized through variables so a collapse cannot fight the
  // responsive breakpoints, and the centre stays `minmax(0, 1fr)`.
  assert.match(
    css,
    /\.workbench-body \{[\s\S]{0,160}grid-template-columns: var\(--wb-left\) minmax\(0, 1fr\) var\(--wb-right\);/,
  );
  assert.match(css, /\.workbench\[data-left-rail='collapsed'\] \{[\s\S]{0,40}--wb-left: 52px;/);
  assert.match(css, /\.workbench\[data-right-rail='collapsed'\] \{[\s\S]{0,40}--wb-right: 52px;/);
  // Collapsing hides the panel content but never removes the navigation rail.
  assert.match(
    css,
    /\.workbench\[data-left-rail='collapsed'\] \.workbench-left-panel \{[\s\S]{0,20}display: none;/,
  );
  assert.doesNotMatch(css, /data-left-rail='collapsed'\] \.workbench-nav-rail \{[\s\S]{0,20}display: none;/);
  // No authority moves with the layout.
  assert.doesNotMatch(appSource, /collapse[\s\S]{0,80}(api\.|invoke\()/i);
});

test('#3606 the collapsed right rail is a real summary, never an invented count', () => {
  const markup = shellMarkup({ status: STATUS, health: HEALTH, runList: RUN_LIST }, 'easy', 'ko');
  const summary = /<div class="workbench-tools-summary"[^>]*>([\s\S]*?)<\/div>/.exec(markup);
  assert.ok(summary, 'the compact summary strip exists');
  const body = summary[1] ?? '';
  assert.match(body, /data-mini-role="connection"/);
  assert.match(body, /data-mini-role="readiness"/);
  // The values are the canonical ones, spelled out — never a bare number.
  assert.match(body, /data-canonical-state="ONLINE"/);
  assert.match(body, /data-canonical-state="RUNNING"/);
  assert.match(body, /연결됨/);
  assert.match(body, /준비됨/);
  assert.doesNotMatch(body, /data-progress-source|data-approvals-source|data-artifacts-source/);
  assert.doesNotMatch(body, /\d+\s*건/);
  // It is only shown while the rail is collapsed.
  assert.match(css, /\.workbench-tools-summary \{[\s\S]{0,40}display: none;/);
  assert.match(
    css,
    /\.workbench\[data-right-rail='collapsed'\] \.workbench-tools-summary \{[\s\S]{0,60}display: flex;/,
  );
});

// ── 3. keyboard ─────────────────────────────────────────────────────────────

test('#3606 only the bounded workbench shortcuts are recognised', () => {
  const base = {
    key: '',
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    targetIsTextField: false,
  };
  const at = (over: Partial<typeof base>): string | null =>
    resolveWorkbenchShortcut({ ...base, ...over });

  assert.equal(at({ key: 'k', ctrlKey: true }), 'search');
  assert.equal(at({ key: 'K', ctrlKey: true }), 'search');
  assert.equal(at({ key: 'k', metaKey: true }), 'search');
  assert.equal(at({ key: 'b', ctrlKey: true }), 'toggle-left-rail');
  assert.equal(at({ key: 'B', metaKey: true }), 'toggle-left-rail');
  assert.equal(at({ key: 'b', ctrlKey: true, shiftKey: true }), 'toggle-right-rail');
  assert.equal(at({ key: 'B', metaKey: true, shiftKey: true }), 'toggle-right-rail');
  assert.equal(at({ key: 'Escape' }), 'dismiss');

  // Rail toggles never hijack a text field; search and Escape still work.
  assert.equal(at({ key: 'b', ctrlKey: true, targetIsTextField: true }), null);
  assert.equal(at({ key: 'b', ctrlKey: true, shiftKey: true, targetIsTextField: true }), null);
  assert.equal(at({ key: 'k', ctrlKey: true, targetIsTextField: true }), 'search');
  assert.equal(at({ key: 'Escape', targetIsTextField: true }), 'dismiss');

  // Nothing else is captured: no execution, approval, Git or process shortcut.
  for (const over of [
    { key: 'g', ctrlKey: true },
    { key: 'G', ctrlKey: true, shiftKey: true },
    { key: 'p', ctrlKey: true, shiftKey: true },
    { key: 'Enter', ctrlKey: true },
    { key: 'j', ctrlKey: true },
    { key: 'k', altKey: true },
    { key: 'b' },
    { key: 'Escape', ctrlKey: true },
    { key: 'Escape', shiftKey: true },
    { key: 'x', ctrlKey: true, shiftKey: true, altKey: true },
  ]) {
    assert.equal(at(over), null, JSON.stringify(over));
  }
});

test('#3606 the advertised shortcut list matches the resolved behaviour', () => {
  assert.deepEqual({ ...WORKBENCH_SHORTCUTS }, {
    search: 'Ctrl/Cmd+K',
    toggleLeftRail: 'Ctrl/Cmd+B',
    toggleRightRail: 'Ctrl/Cmd+Shift+B',
    dismiss: 'Escape',
  });
  // The shortcuts are discoverable from the controls themselves.
  const markup = shellMarkup({}, 'easy', 'en');
  assert.match(markup, /\(Ctrl\/Cmd\+B\)/);
  assert.match(markup, /\(Ctrl\/Cmd\+Shift\+B\)/);
  // ...and the handler never calls the bridge.
  const listener = /addEventListener\('keydown'[\s\S]*?\}, \[\]\);/.exec(appSource);
  assert.ok(listener, 'a keydown listener is registered');
  assert.doesNotMatch(listener[0], /api\./);
  assert.doesNotMatch(listener[0], /actions\./);
});

// ── 4. session navigation ───────────────────────────────────────────────────

test('#3606 the session list carries only canonical session state', () => {
  const markup = render(
    createElement(SessionListPanel, {
      conversations: CONVERSATIONS,
      selectedConversationId: CHAT_A,
      onSelectConversation: () => undefined,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(markup, /data-session-source="canonical"/);
  assert.match(markup, /data-session-count="2"/);
  assert.match(markup, /세션 2/);
  // The canonical timestamp travels as an attribute and as a <time> element.
  for (const item of CONVERSATIONS.conversations) {
    assert.match(markup, new RegExp(`data-updated-at="${item.updatedAt}"`));
    assert.match(markup, new RegExp(`dateTime="${item.updatedAt}"`, 'i'));
  }
  assert.match(markup, new RegExp(`data-conversation-id="${CHAT_A}"[^>]*data-session-selected="true"`));
  assert.match(markup, /aria-current="true"/);
  // No invented session state.
  for (const forbidden of ['pinned', '고정', 'unread', '안 읽음', '읽지 않음', 'badge', 'project group']) {
    assert.doesNotMatch(markup, new RegExp(forbidden, 'i'), forbidden);
  }
});

test('#3606 a session timestamp is only formatted, never fabricated', () => {
  assert.equal(formatSessionStamp('ko', 'not-a-date'), '');
  assert.equal(formatSessionStamp('en', ''), '');
  const stamp = formatSessionStamp('en', '2026-10-07T02:05:00Z');
  assert.ok(stamp.length > 0);
  assert.doesNotMatch(stamp, /NaN|Invalid/);
});

// ── 5. truthfulness preserved ───────────────────────────────────────────────

test('#3606 unsupported controls are still non-executable after the density pass', () => {
  const markup = shellMarkup({ status: STATUS, health: HEALTH, runList: RUN_LIST }, 'easy', 'ko');
  for (const section of WORKBENCH_UNSUPPORTED_SECTIONS) {
    assert.match(markup, new RegExp(`data-nav-section="${section}"[^>]*data-unsupported="true"`));
    assert.match(markup, new RegExp(`data-nav-section="${section}"[^>]*disabled`));
  }
  assert.equal(WORKBENCH_NAV_SECTIONS.length, 6);
  // Git stays a placeholder with no fabricated changed files.
  assert.match(markup, /data-git-authority="none"/);
  // Task submission is still disabled with an explicit reason.
  const send = /<button[^>]*workbench-composer-send[^>]*>/.exec(markup);
  assert.ok(send);
  assert.match(send[0], /disabled/);
  assert.match(send[0], /data-unavailable-reason="no_task_submit_authority"/);
});

test('#3606 no model or provider selector was added by the interaction layer', () => {
  const markup = shellMarkup(
    { status: STATUS, health: HEALTH, conversationList: CONVERSATIONS },
    'easy',
    'en',
  );
  assert.doesNotMatch(markup, /<select/i);
  assert.doesNotMatch(markup, /data-model/i);
  assert.doesNotMatch(markup, /provider/i);
  for (const forbidden of ['useModel', 'selectProvider', 'successor', 'modelId']) {
    assert.doesNotMatch(appSource, new RegExp(forbidden), forbidden);
  }
  assert.match(appSource, /MODEL_SELECTOR_ACTIVATION=0/);
});

test('#3606 the interaction layer adds no IPC channel and no new capability', () => {
  const allowed = [
    'getStatus',
    'runnerStart',
    'runnerStop',
    'runnerHealth',
    'submitPairingDeepLink',
    'getBoundedLog',
    'chooseWorkspaceRoot',
    'listWorkspaceDirectory',
    'clearWorkspaceRoot',
    'searchWorkspace',
    'listConversations',
    'readConversation',
    'listRuns',
    'readRun',
  ];
  const invoked = [...appSource.matchAll(/\bapi\.([A-Za-z]+)\(/g)].map((match) => match[1] ?? '');
  assert.ok(invoked.length > 0);
  for (const name of invoked) {
    assert.ok(allowed.includes(name), `renderer invoked a non-allowlisted method: ${name}`);
  }
  assert.doesNotMatch(appSource, /ipcRenderer/);
  // The IPC contract itself is untouched by this slice.
  const contract = readFileSync(path.join(packageRoot, 'src', 'contract', 'ipc.ts'), 'utf8');
  const allowlistBlock = /export const IPC_CHANNELS = \[([\s\S]*?)\] as const;/.exec(contract);
  assert.ok(allowlistBlock, 'the IPC allowlist block is present');
  const channels = [...(allowlistBlock[1] ?? '').matchAll(/'padiem:shell:[a-z-]+'/g)];
  assert.equal(channels.length, 14);
});

// ── 6. density, languages and views ─────────────────────────────────────────

test('#3606 the workbench chrome is denser than the dashboard it replaced', () => {
  assert.match(css, /\.workbench-topbar \{[\s\S]{0,60}padding: 6px 14px;/);
  assert.match(css, /\.workbench \.panel \{[\s\S]{0,60}border-radius: 10px;/);
  assert.match(css, /\.workbench \.conversation-workspace-header \{[\s\S]{0,40}min-height: 34px;/);
  assert.match(css, /\.workbench \.run-activity-header \{[\s\S]{0,40}min-height: 32px;/);
  assert.match(css, /\.workbench-tabs \{/);
  assert.match(css, /\.workbench-center \{[\s\S]{0,120}gap: 8px;/);
});

test('#3606 Korean/English and Easy/Advanced are all still produced', () => {
  const ko = shellMarkup({ conversationList: CONVERSATIONS }, 'easy', 'ko');
  const en = shellMarkup({ conversationList: CONVERSATIONS }, 'easy', 'en');
  assert.match(ko, /aria-label="작업 탭"/);
  assert.match(en, /aria-label="Task tabs"/);
  assert.notEqual(ko, en);

  const easy = shellMarkup({ conversationList: CONVERSATIONS }, 'easy', 'ko');
  const advanced = shellMarkup({ conversationList: CONVERSATIONS }, 'advanced', 'ko');
  assert.doesNotMatch(easy, /data-advanced="true"[\s\S]{0,200}tabs|탭은 Padiem의 기존 대화/);
  assert.match(advanced, /탭은 Padiem의 기존 대화를 그대로 가리킵니다/);
  assert.match(advanced, /data-advanced="true"/);
});

test('#3606 the centre workspace is still the primary pane in every layout rule', () => {
  for (const block of css.matchAll(/grid-template-columns:([^;]+);/g)) {
    const value = (block[1] ?? '').trim();
    if (value.includes('var(--wb-left)') || value.includes('minmax(0, 1fr)')) {
      assert.match(value, /minmax\(0, 1fr\)/, `centre must be the flexible column: ${value}`);
    }
  }
});
