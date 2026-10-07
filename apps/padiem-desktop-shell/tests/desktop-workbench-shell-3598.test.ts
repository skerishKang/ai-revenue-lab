/**
 * #3598 — renderer tests for the ZCode-derived Padiem desktop workbench shell.
 *
 * Covers the first-slice IA: the three-pane workbench, the left task/workspace
 * navigation, the centre Claw workspace, the right tools/status rail and the
 * bottom composer — plus the two things that must not regress while the IA
 * changes: the existing connection/readiness/workspace surfaces and the #3591
 * bounded workspace search composition.
 *
 * Everything is rendered to static markup through the real modules, so the
 * assertions see the DOM a user would see (minus hydration). Truthfulness is
 * asserted negatively as well: an unavailable canonical source must never be
 * rendered as a zero, and no control without backend authority may look
 * executable.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  DEFAULT_WORKBENCH_SECTION,
  INITIAL_SHELL_VIEW_STATE,
  SessionListPanel,
  ShellView,
  TaskComposer,
  ToolsStatusPanel,
  WORKBENCH_NAV_SECTIONS,
  WORKBENCH_UNSUPPORTED_SECTIONS,
  WorkbenchNavRail,
  WorkspacePanel,
  isWorkbenchSectionSupported,
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
    {
      name: 'src',
      relativePath: 'src',
      kind: 'directory',
      sizeBytes: null,
      modifiedAt: null,
    },
    {
      name: 'quote-draft.docx',
      relativePath: 'quote-draft.docx',
      kind: 'file',
      sizeBytes: 4096,
      modifiedAt: '2026-10-02T09:00:00.000Z',
    },
  ],
  truncated: false,
  maxEntries: 200,
  errorCode: null,
};

const STATUS: ShellStatus = {
  deviceState: 'ONLINE',
  deviceStateRevision: 3,
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

const LOG: BoundedLogResponse = { lines: ['runner: started'], truncated: false, redactionApplied: true };

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
      createdAt: '2026-10-02T09:00:00Z',
      updatedAt: '2026-10-02T09:03:21Z',
      resultSummary: '견적서 초안 작성을 진행합니다.',
      artifact: {
        documentId: 'doc_' + '1'.repeat(24),
        filename: 'quote-draft.docx',
        mediaType: 'application/msword',
      },
      conversationId: null,
      workspaceId: null,
    },
    {
      runId: 'run_b3f9d2e85c8f7146ba0d3f22',
      status: 'waiting_approval',
      channel: 'claw_automation',
      action: 'order_draft',
      title: '[CLAW_AUTOMATION] order_draft',
      createdAt: '2026-10-02T08:00:00Z',
      updatedAt: '2026-10-02T08:01:00Z',
      resultSummary: null,
      artifact: null,
      conversationId: null,
      workspaceId: null,
    },
    {
      runId: 'run_c4a0e3f96d9a8257cb1e4f33',
      status: 'completed',
      channel: 'web',
      action: 'summary',
      title: '[WEB] summary',
      createdAt: '2026-10-01T08:00:00Z',
      updatedAt: '2026-10-01T08:02:00Z',
      resultSummary: null,
      artifact: null,
      conversationId: null,
      workspaceId: null,
    },
  ],
};

const CONVERSATIONS: CanonicalConversationListResponse = {
  ok: true,
  configured: true,
  errorCode: null,
  conversations: [
    {
      id: 'chat_' + 'a'.repeat(32),
      title: '견적 초안',
      createdAt: '2026-10-02T09:00:00Z',
      updatedAt: '2026-10-02T09:03:21Z',
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

// --- 1. the three-pane workbench shell -------------------------------------

test('#3598 the desktop shell is a three-pane workbench, not the old dashboard', () => {
  const markup = shellMarkup({ status: STATUS, health: HEALTH, log: LOG });
  assert.match(markup, /data-workbench-ia="zcode-derived"/);
  // top shell
  assert.match(markup, /workbench-topbar/);
  assert.match(markup, /data-current-task="true"/);
  assert.match(markup, /data-workspace-context="true"/);
  // three panes
  assert.match(markup, /workbench-nav-rail/);
  assert.match(markup, /workbench-left/);
  assert.match(markup, /workbench-center/);
  assert.match(markup, /workbench-tools/);
  // bottom composer
  assert.match(markup, /workbench-composer/);
  // the legacy layout markers the previous stage pinned are still present
  assert.match(markup, /workspace-project-rail/);
  assert.match(markup, /workspace-main/);
  assert.match(markup, /workspace-local-rail/);
});

test('#3598 the top shell names the current task and the working context', () => {
  const markup = shellMarkup({ workspaceRoot: ROOT, workspaceListing: LISTING }, 'easy', 'ko');
  assert.match(markup, /현재 작업/);
  assert.match(markup, /작업 위치/);
  assert.match(markup, /customer-project/);
  // No conversation is selected, so the honest answer is "nothing yet".
  assert.match(markup, /아직 선택된 작업이 없습니다/);
});

// --- 2. left navigation -----------------------------------------------------

test('#3598 the left navigation offers the ZCode-derived task/workspace entries', () => {
  const markup = render(
    createElement(WorkbenchNavRail, {
      active: DEFAULT_WORKBENCH_SECTION,
      onSelect: () => undefined,
      locale: 'ko',
    }),
  );
  for (const label of ['새 작업', '검색', '자동화', '플러그인', '프로젝트', '세션']) {
    assert.match(markup, new RegExp(label), label);
  }
  assert.deepEqual(
    [...WORKBENCH_NAV_SECTIONS],
    ['new-task', 'search', 'automations', 'plugins', 'projects', 'sessions'],
  );
});

test('#3598 only one navigation entry is the active page and it is the default section', () => {
  const nav = render(
    createElement(WorkbenchNavRail, {
      active: DEFAULT_WORKBENCH_SECTION,
      onSelect: () => undefined,
      locale: 'en',
    }),
  );
  const active = [...nav.matchAll(/aria-current="page"/g)];
  assert.equal(active.length, 1, 'exactly one navigation entry is current');
  assert.match(nav, /data-nav-section="projects"[^>]*aria-current="page"/);
  // The shell opens on that same section.
  assert.match(shellMarkup({}, 'easy', 'en'), /data-left-section="projects"/);
});

test('#3598 navigation entries without backend authority are visibly non-executable', () => {
  const markup = render(
    createElement(WorkbenchNavRail, {
      active: 'projects',
      onSelect: () => undefined,
      locale: 'en',
    }),
  );
  assert.deepEqual([...WORKBENCH_UNSUPPORTED_SECTIONS], ['new-task', 'automations', 'plugins']);
  for (const section of WORKBENCH_UNSUPPORTED_SECTIONS) {
    assert.equal(isWorkbenchSectionSupported(section), false);
    // disabled + aria-disabled + an explicit data marker, plus a visible badge.
    assert.match(markup, new RegExp(`data-nav-section="${section}"[^>]*data-unsupported="true"`));
    assert.match(markup, new RegExp(`data-nav-section="${section}"[^>]*disabled`));
    assert.match(markup, new RegExp(`data-nav-section="${section}"[^>]*aria-disabled="true"`));
  }
  assert.equal(isWorkbenchSectionSupported('projects'), true);
  assert.equal(isWorkbenchSectionSupported('sessions'), true);
  assert.equal(isWorkbenchSectionSupported('search'), true);
  assert.match(markup, /Coming later/);
  // The supported entries are not marked unsupported.
  assert.match(markup, /data-nav-section="sessions"[^>]*data-unsupported="false"/);
});

test('#3598 navigation entries are real buttons with accessible names and visible focus', () => {
  const markup = render(
    createElement(WorkbenchNavRail, {
      active: 'sessions',
      onSelect: () => undefined,
      locale: 'ko',
    }),
  );
  assert.doesNotMatch(markup, /<div[^>]*data-nav-section/);
  const buttons = [...markup.matchAll(/<button[^>]*data-nav-section="[^"]*"[^>]*>/g)];
  assert.equal(buttons.length, WORKBENCH_NAV_SECTIONS.length);
  for (const button of buttons) {
    assert.match(button[0], /aria-label="/, `missing accessible name on ${button[0]}`);
  }
  const css = readFileSync(path.join(rendererDir, 'shell.css'), 'utf8');
  assert.match(css, /:focus-visible/);
  assert.match(css, /\.workbench-nav-item\.active/);
});

// --- 3. centre workspace ----------------------------------------------------

test('#3598 the centre pane hosts the Claw conversation and the run/result surface', () => {
  const markup = shellMarkup({ runList: RUN_LIST, conversationList: CONVERSATIONS }, 'easy', 'ko');
  assert.match(markup, /data-center-role="claw-workspace"/);
  assert.match(markup, /data-conversation-source="canonical"/);
  assert.match(markup, /data-run-source="canonical"/);
  assert.match(markup, /최근 작업/);
  // The centre keeps only the transcript; the session list is navigation.
  assert.doesNotMatch(markup, /class="conversation-list"/);
  assert.match(markup, /탐색에서 세션을 열고 이어볼 대화를 고르면 여기에 표시됩니다/);
});

test('#3598 the centre conversation surface stays fail-closed without the canonical source', () => {
  const markup = shellMarkup({}, 'easy', 'ko');
  assert.match(markup, /data-conversation-source="canonical-required"/);
  assert.match(markup, /data-run-source="canonical-required"/);
  assert.match(markup, /새 대화를 만들지 않습니다/);
});

test('#3598 the session navigation list is canonical and offers no new conversation action', () => {
  const canonical = render(
    createElement(SessionListPanel, {
      conversations: CONVERSATIONS,
      selectedConversationId: CONVERSATIONS.conversations[0]?.id ?? null,
      onSelectConversation: () => undefined,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(canonical, /data-session-source="canonical"/);
  assert.match(canonical, /견적 초안/);
  assert.doesNotMatch(canonical, /새 대화/);

  const pending = render(
    createElement(SessionListPanel, {
      conversations: null,
      selectedConversationId: null,
      onSelectConversation: () => undefined,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(pending, /data-session-source="canonical-required"/);
  assert.match(pending, /기존 대화 연결을 준비 중입니다/);
  assert.doesNotMatch(pending, /chat_[0-9a-f]/);
});

// --- 4. right tools/status rail ---------------------------------------------

test('#3598 the tools rail projects real canonical run records', () => {
  const markup = render(
    createElement(ToolsStatusPanel, { runs: RUN_LIST, locale: 'ko', advanced: false }),
  );
  assert.match(markup, /data-tools-rail="true"/);
  assert.match(markup, /data-progress-source="canonical"/);
  assert.match(markup, /data-approvals-source="canonical"/);
  assert.match(markup, /data-artifacts-source="canonical"/);
  // 3 runs, 2 of them still in flight; 1 waiting for approval; 1 with an artifact.
  assert.match(markup, /작업 3건 · 진행 중 2건/);
  assert.match(markup, /승인 대기 1건/);
  assert.match(markup, /결과 파일 1건/);
  // Canonical ids never leak into this rail.
  assert.doesNotMatch(markup, /run_[0-9a-f]/);
});

test('#3598 an unavailable canonical source is said out loud, never shown as zero', () => {
  for (const runs of [null, { ...RUN_LIST, ok: false, runs: [] }]) {
    const markup = render(createElement(ToolsStatusPanel, { runs, locale: 'ko', advanced: false }));
    assert.match(markup, /data-progress-source="canonical-required"/);
    assert.match(markup, /작업 기록 연결을 준비 중입니다/);
    assert.match(markup, /승인 상태를 확인하는 중입니다/);
    assert.match(markup, /결과 파일 연결을 준비 중입니다/);
    // A zero would read as "nothing pending", which is a claim we cannot make.
    assert.doesNotMatch(markup, /작업 0건/);
    assert.doesNotMatch(markup, /승인 대기 중인 작업이 없습니다/);
    assert.doesNotMatch(markup, /아직 결과 파일이 없습니다/);
  }
});

test('#3598 an empty canonical run history is a valid answer, not a failure', () => {
  const markup = render(
    createElement(ToolsStatusPanel, {
      runs: { ...RUN_LIST, runs: [] },
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(markup, /data-progress-source="canonical"/);
  assert.match(markup, /작업 0건 · 진행 중 0건/);
  assert.match(markup, /승인 대기 중인 작업이 없습니다/);
  assert.match(markup, /아직 결과 파일이 없습니다/);
});

test('#3598 the Git placeholder is non-executable and fabricates no changed files', () => {
  const markup = render(
    createElement(ToolsStatusPanel, { runs: RUN_LIST, locale: 'ko', advanced: false }),
  );
  assert.match(markup, /data-git-authority="none"/);
  assert.match(markup, /Git 도구는 아직 연결되지 않았습니다/);
  const gitBlock = markup.slice(markup.indexOf('data-git-authority="none"'));
  for (const control of ['브랜치', '커밋', '푸시']) {
    assert.match(gitBlock, new RegExp(`${control}`));
  }
  const gitButtons = [...gitBlock.matchAll(/<button[^>]*>/g)];
  assert.equal(gitButtons.length, 3);
  for (const button of gitButtons) {
    assert.match(button[0], /disabled/);
    assert.match(button[0], /data-unsupported="true"/);
  }
  assert.doesNotMatch(markup, /modified:/i);
  assert.doesNotMatch(markup, /\+\d+ -\d+/);
});

// --- 5. bottom composer -----------------------------------------------------

test('#3598 the composer is a shell: local input, disabled run action', () => {
  const markup = render(createElement(TaskComposer, { status: STATUS, health: HEALTH, locale: 'ko' }));
  assert.match(markup, /data-composer-authority="read-only"/);
  assert.match(markup, /workbench-task-input/);
  assert.match(markup, /작업 입력/);
  assert.match(markup, /작업 전송은 아직 연결되지 않았습니다/);
  const send = /<button[^>]*workbench-composer-send[^>]*>/.exec(markup);
  assert.ok(send, 'the run action exists');
  assert.match(send[0], /disabled/);
  assert.match(send[0], /aria-disabled="true"/);
  assert.match(send[0], /data-unsupported="true"/);
  assert.match(send[0], /data-unavailable-reason="no_task_submit_authority"/);
});

test('#3598 the composer reports provider-neutral execution facts only', () => {
  const running = render(
    createElement(TaskComposer, { status: STATUS, health: HEALTH, locale: 'ko' }),
  );
  assert.match(running, /data-execution-mode="local"/);
  assert.match(running, /실행 방식: 이 컴퓨터/);
  assert.match(running, /data-computer-access="RUNNING"/);
  assert.match(running, /컴퓨터 접근: 준비됨/);

  // Unknown state is reported as unknown, not optimistically as ready.
  const unknown = render(createElement(TaskComposer, { status: null, health: null, locale: 'ko' }));
  assert.match(unknown, /data-computer-access="UNKNOWN"/);
  assert.match(unknown, /확인 중/);
});

test('#3598 the composer has no model or provider selector', () => {
  const markup = shellMarkup({ status: STATUS, health: HEALTH, log: LOG }, 'easy', 'en');
  assert.doesNotMatch(markup, /<select/i);
  assert.doesNotMatch(markup, /data-model/i);
  assert.doesNotMatch(markup, /provider/i);
  // The renderer implements no model/provider selection at all.
  const source = readFileSync(path.join(rendererDir, 'app.tsx'), 'utf8');
  for (const forbidden of ['useModel', 'selectProvider', 'successor', 'modelId']) {
    assert.doesNotMatch(source, new RegExp(forbidden), forbidden);
  }
  // ...and the policy constant is pinned in the module header.
  assert.match(source, /MODEL_SELECTOR_ACTIVATION=0/);
});

// --- 6. preserved surfaces --------------------------------------------------

test('#3598 the existing connection and readiness surfaces survive the re-IA', () => {
  const markup = shellMarkup({ status: STATUS, health: HEALTH }, 'easy', 'ko');
  assert.match(markup, /컴퓨터 연결/);
  assert.match(markup, /연결 다시 확인/);
  assert.match(markup, /작업 준비/);
  assert.match(markup, /준비하기/);
  assert.match(markup, /일시 정지/);
  assert.match(markup, /설정/);
  assert.match(markup, /This computer|이 컴퓨터/);
});

test('#3598 the existing workspace selection surface survives the re-IA', () => {
  const markup = shellMarkup({ workspaceRoot: ROOT, workspaceListing: LISTING }, 'easy', 'ko');
  assert.match(markup, /작업 폴더/);
  assert.match(markup, /customer-project/);
  assert.match(markup, /폴더 변경/);
  // Easy view still hides the absolute local path.
  assert.doesNotMatch(markup, /C:\\Users\\person/);
});

test('#3598 the Advanced diagnostics are still reachable, now inside the tools rail', () => {
  const markup = shellMarkup(
    { status: STATUS, health: HEALTH, log: LOG },
    'advanced',
    'ko',
  );
  assert.match(markup, /연결 진단/);
  assert.match(markup, /실행 기록/);
  assert.match(markup, /프로세스 경계/);
  assert.match(markup, /4242/);
  assert.match(markup, /data-advanced="true"/);
});

// --- 7. #3591 search composition --------------------------------------------

test('#3598 the #3591 workspace search composes into the left navigation', () => {
  const plain = render(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: LISTING,
      search: null,
      selectedEntry: null,
      actions: NOOP_ACTIONS,
      locale: 'ko',
      advanced: false,
    }),
  );
  // #3583's bounded search form is untouched and still the only search surface.
  assert.match(plain, /class="workspace-search"/);
  assert.match(plain, /id="workspace-search-input"/);
  assert.match(plain, /data-search-focus="false"/);
  assert.doesNotMatch(plain, /autofocus/i);

  const focused = render(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: LISTING,
      search: null,
      selectedEntry: null,
      actions: NOOP_ACTIONS,
      locale: 'ko',
      advanced: false,
      focusSearch: true,
    }),
  );
  assert.match(focused, /data-search-focus="requested"/);
  assert.match(focused, /autofocus/i);
});

test('#3598 the search surface adds no renderer-side filesystem authority', () => {
  const source = readFileSync(path.join(rendererDir, 'app.tsx'), 'utf8');
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
  const invoked = [...source.matchAll(/\bapi\.([A-Za-z]+)\(/g)].map((match) => match[1] ?? '');
  assert.ok(invoked.length > 0);
  for (const name of invoked) {
    assert.ok(allowed.includes(name), `renderer invoked a non-allowlisted method: ${name}`);
  }
  // The workbench adds no new channel: no generic invoke, no raw path input.
  assert.doesNotMatch(source, /ipcRenderer/);
  assert.doesNotMatch(source, /invoke\(/);
});

// --- 8. responsive collapse -------------------------------------------------

test('#3598 both rails collapse at narrow widths and the centre stays primary', () => {
  const css = readFileSync(path.join(rendererDir, 'shell.css'), 'utf8');
  assert.match(css, /@media \(max-width: 1180px\)/);
  assert.match(css, /@media \(max-width: 960px\)/);
  assert.match(css, /@media \(max-width: 720px\)/);
  // The rails are collapsed by hiding labels/badges and by stacking the tools
  // rail below the centre, so the centre pane never shrinks to a strip.
  assert.match(css, /\.workbench-nav-label,[\s\S]{0,80}display: none;/);
  assert.match(css, /\.workbench-tools \{[\s\S]{0,200}grid-column: 1 \/ -1;/);
  assert.match(css, /\.workbench-body \{[\s\S]{0,120}grid-template-columns: minmax\(0, 1fr\);/);
  // Minimum usable width: the composer and the top bar both reflow.
  assert.match(css, /\.workbench-composer \{[\s\S]{0,120}grid-template-columns: minmax\(0, 1fr\);/);
});

// --- 9. accessibility -------------------------------------------------------

test('#3598 state is never carried by colour alone', () => {
  const markup = shellMarkup({ status: STATUS, health: HEALTH, runList: RUN_LIST }, 'easy', 'ko');
  // Canonical state travels as an attribute next to its wording.
  assert.match(markup, /data-canonical-state="ONLINE"/);
  assert.match(markup, /data-canonical-state="RUNNING"/);
  assert.match(markup, /data-computer-access="RUNNING"/);
  assert.match(markup, /data-progress-source="canonical"/);
  assert.match(markup, /data-approvals-source="canonical"/);
  assert.match(markup, /data-artifacts-source="canonical"/);
});

test('#3598 the composer input has a programmatic label', () => {
  const markup = render(createElement(TaskComposer, { status: null, health: null, locale: 'ko' }));
  assert.match(markup, /for="workbench-task-input"|htmlFor="workbench-task-input"/);
  assert.match(markup, /id="workbench-task-input"/);
  const css = readFileSync(path.join(rendererDir, 'shell.css'), 'utf8');
  assert.match(css, /\.visually-hidden \{/);
});
