import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  ConversationWorkspacePanel,
  INITIAL_SHELL_VIEW_STATE,
  RunActivityPanel,
  ShellView,
  WorkspacePanel,
  type ShellActions,
} from '../src/renderer/app.js';
import type {
  CanonicalRunListResponse,
  WorkspaceListResponse,
  WorkspaceRootResponse,
} from '../src/renderer/types.js';

const ACTIONS: ShellActions = {
  refresh: async () => undefined,
  start: async () => undefined,
  stop: async () => undefined,
  submitPairingDeepLink: async () => undefined,
  chooseWorkspaceRoot: async () => undefined,
  openWorkspaceDirectory: async () => undefined,
  clearWorkspaceRoot: async () => undefined,
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
  directory: 'src',
  entries: [
    {
      name: 'components',
      relativePath: 'src/components',
      kind: 'directory',
      sizeBytes: null,
      modifiedAt: '2026-10-01T09:00:00.000Z',
    },
    {
      name: 'index.ts',
      relativePath: 'src/index.ts',
      kind: 'file',
      sizeBytes: 2048,
      modifiedAt: '2026-10-02T09:00:00.000Z',
    },
    {
      name: 'linked',
      relativePath: 'src/linked',
      kind: 'link',
      sizeBytes: null,
      modifiedAt: null,
    },
  ],
  truncated: false,
  maxEntries: 200,
  errorCode: null,
};

test('#3436 Easy workspace shows project navigation but not the absolute local path', () => {
  const markup = renderToStaticMarkup(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: LISTING,
      selectedEntry: null,
      actions: ACTIONS,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(markup, /작업 폴더/);
  assert.match(markup, /customer-project/);
  assert.match(markup, /components/);
  assert.match(markup, /index\.ts/);
  assert.doesNotMatch(markup, /C:\\Users\\person/);
});
test('#3436 Advanced workspace may show the user-selected local path as diagnostics', () => {
  const markup = renderToStaticMarkup(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: LISTING,
      selectedEntry: null,
      actions: ACTIONS,
      locale: 'en',
      advanced: true,
    }),
  );
  assert.match(markup, /Work folder/);
  assert.match(markup, /C:\\Users\\person\\customer-project/);
  assert.match(markup, /data-advanced="true"/);
});

test('#3436 no-root state offers a native folder selection action', () => {
  const markup = renderToStaticMarkup(
    createElement(WorkspacePanel, {
      root: null,
      listing: null,
      selectedEntry: null,
      actions: ACTIONS,
      locale: 'en',
      advanced: false,
    }),
  );
  assert.match(markup, /Choose folder/);
  assert.match(markup, /Choose a folder to browse its files and subfolders safely/);
});

test('#3436 project browser renders a root-relative breadcrumb for the open folder', () => {
  const markup = renderToStaticMarkup(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: LISTING,
      selectedEntry: null,
      actions: ACTIONS,
      locale: 'en',
      advanced: false,
    }),
  );
  assert.match(markup, /workspace-breadcrumb/);
  assert.match(markup, /customer-project/);
  // The current location is the project's basename plus the relative segment:
  // never an absolute path, in either view mode.
  assert.match(markup, /aria-current="location"/);
  assert.doesNotMatch(markup, /C:\\Users\\person/);
});

test('#3436 selecting an entry shows its read-only metadata detail', () => {
  const markup = renderToStaticMarkup(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: LISTING,
      selectedEntry: LISTING.entries[1] ?? null,
      actions: ACTIONS,
      locale: 'en',
      advanced: false,
    }),
  );
  assert.match(markup, /data-selected-path="src\/index\.ts"/);
  assert.match(markup, /data-selected="true"/);
  assert.match(markup, /File/);
  assert.match(markup, /2\.0 KB/);
  assert.match(markup, /src\/index\.ts/);
});

test('#3436 project browser exposes no write, rename, delete or create control', () => {
  const markup = renderToStaticMarkup(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: LISTING,
      selectedEntry: LISTING.entries[1] ?? null,
      actions: ACTIONS,
      locale: 'ko',
      advanced: true,
    }),
  );
  for (const forbidden of [
    '삭제',
    '이름 바꾸',
    '새 폴더',
    '새 파일',
    '저장',
    'Delete',
    'Rename',
    'New folder',
    'Save',
  ]) {
    assert.doesNotMatch(markup, new RegExp(forbidden, 'i'), forbidden);
  }
});

test('#3436 a depth-capped listing says so instead of rendering an empty folder', () => {
  const depthCapped: WorkspaceListResponse = {
    ...LISTING,
    ok: false,
    directory: 'a/b/c',
    entries: [],
    errorCode: 'depth_exceeded',
  };
  const markup = renderToStaticMarkup(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: depthCapped,
      selectedEntry: null,
      actions: ACTIONS,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(markup, /data-error-code="depth_exceeded"/);
  assert.match(markup, /폴더 깊이 한도/);
});

test('#3436 the local root never presents itself as the canonical Padiem workspace', () => {
  const markup = renderToStaticMarkup(
    createElement(WorkspacePanel, {
      root: ROOT,
      listing: LISTING,
      selectedEntry: null,
      actions: ACTIONS,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(markup, /로컬 작업 공간/);
  assert.match(markup, /대체하거나 변경하지 않습니다/);
});

test('#3436 B2a conversation surface is fail-closed until canonical projection exists', () => {
  const markup = renderToStaticMarkup(
    createElement(ConversationWorkspacePanel, {
      locale: 'ko',
      advanced: false,
      conversations: null,
      selectedConversation: null,
      onSelectConversation: () => undefined,
    }),
  );
  assert.match(markup, /data-conversation-source="canonical-required"/);
  assert.match(markup, /새 대화를 만들지 않습니다/);
  assert.doesNotMatch(markup, /<textarea/i);
  assert.doesNotMatch(markup, /contenteditable/i);
  assert.doesNotMatch(markup, /<input/i);
  assert.doesNotMatch(markup, /conversation[_-]?id/i);
  assert.doesNotMatch(markup, /기존 Padiem Chat\/Claw 대화가 기준/);
});

test('#3436 B2a Desktop layout composes project, Claw workspace and local status rails', () => {
  const markup = renderToStaticMarkup(
    createElement(ShellView, {
      state: {
        ...INITIAL_SHELL_VIEW_STATE,
        workspaceRoot: ROOT,
        workspaceListing: LISTING,
      },
      preferences: { locale: 'en', theme: 'system', view: 'easy' },
      actions: ACTIONS,
      settingsOpen: false,
      onToggleSettings: () => undefined,
      onLocale: () => undefined,
      onTheme: () => undefined,
      onView: () => undefined,
      onCloseSettings: () => undefined,
    }),
  );
  assert.match(markup, /data-desktop-workspace="stage-b"/);
  assert.match(markup, /workspace-project-rail/);
  assert.match(markup, /workspace-main/);
  assert.match(markup, /workspace-local-rail/);
  assert.match(markup, /customer-project/);
  assert.match(markup, /Same-conversation continuity is being prepared for Desktop/);
  assert.match(markup, /This computer/);
});

test('#3436 B2a Advanced layout states the canonical conversation boundary explicitly', () => {
  const markup = renderToStaticMarkup(
    createElement(ConversationWorkspacePanel, {
      locale: 'en',
      advanced: true,
      conversations: null,
      selectedConversation: null,
      onSelectConversation: () => undefined,
    }),
  );
  assert.match(markup, /data-advanced="true"/);
  assert.match(markup, /existing Padiem Chat\/Claw conversation remains canonical/);
  assert.doesNotMatch(markup, /<textarea/i);
});

const CANONICAL_RUN_ID = 'run_a2f8c1d94b7e6035fa9c2e11';
const CANONICAL_CONVERSATION_ID = 'chat_' + 'a'.repeat(32);
const CANONICAL_WORKSPACE_ID = 'ws_padiem_main_01';

const RUN_LIST: CanonicalRunListResponse = {
  ok: true,
  configured: true,
  liveActivitySource: 'not_yet_available',
  errorCode: null,
  runs: [
    {
      runId: CANONICAL_RUN_ID,
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
      conversationId: CANONICAL_CONVERSATION_ID,
      workspaceId: CANONICAL_WORKSPACE_ID,
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
  ],
};

test('#3436 B3a run surface is fail-closed until the canonical projection exists', () => {
  for (const runs of [
    null,
    { ...RUN_LIST, ok: false, errorCode: 'canonical_run_unavailable' as const, runs: [] },
  ]) {
    const markup = renderToStaticMarkup(
      createElement(RunActivityPanel, { locale: 'ko', advanced: false, runs }),
    );
    assert.match(markup, /data-run-source="canonical-required"/);
    assert.match(markup, /새 작업을 만들지 않습니다/);
    // No local run fallback: no invented ids, no invented status rows.
    assert.doesNotMatch(markup, /run_[0-9a-f]/);
    assert.doesNotMatch(markup, /실시간/);
    assert.doesNotMatch(markup, /<textarea/i);
  }
});

test('#3436 B3a Easy run surface speaks product language and hides canonical ids', () => {
  const markup = renderToStaticMarkup(
    createElement(RunActivityPanel, { locale: 'ko', advanced: false, runs: RUN_LIST }),
  );
  assert.match(markup, /data-run-source="canonical"/);
  assert.match(markup, /최근 작업/);
  assert.match(markup, /실행 중/);
  assert.match(markup, /승인 대기/);
  assert.match(markup, /홍길동/);
  assert.match(markup, /견적서 초안 작성을 진행합니다/);
  assert.match(markup, /결과 파일 있음/);
  assert.match(markup, /대화 연결/);
  // Canonical ids and channel vocabulary are Advanced-only diagnostics (#3165).
  assert.doesNotMatch(markup, new RegExp(CANONICAL_RUN_ID));
  assert.doesNotMatch(markup, new RegExp(CANONICAL_CONVERSATION_ID));
  assert.doesNotMatch(markup, new RegExp(CANONICAL_WORKSPACE_ID));
  assert.doesNotMatch(markup, /claw_automation/);
});

test('#3436 B3a Advanced run surface shows canonical ids and the authority note', () => {
  const markup = renderToStaticMarkup(
    createElement(RunActivityPanel, { locale: 'en', advanced: true, runs: RUN_LIST }),
  );
  assert.match(markup, new RegExp(CANONICAL_RUN_ID));
  assert.match(markup, new RegExp(CANONICAL_CONVERSATION_ID));
  assert.match(markup, new RegExp(CANONICAL_WORKSPACE_ID));
  assert.match(markup, /claw_automation/);
  assert.match(markup, /data-advanced="true"/);
  assert.match(markup, /recent-records view, not a live feed/);
});

test('#3436 B3a an empty canonical run history is a valid answer, not a failure', () => {
  const markup = renderToStaticMarkup(
    createElement(RunActivityPanel, {
      locale: 'en',
      advanced: false,
      runs: { ...RUN_LIST, runs: [] },
    }),
  );
  assert.match(markup, /data-run-source="canonical"/);
  assert.match(markup, /No runs to show yet/);
  assert.doesNotMatch(markup, /Run history connection is being prepared/);
});

test('#3436 B3a the workspace layout composes the run activity surface', () => {
  const markup = renderToStaticMarkup(
    createElement(ShellView, {
      state: { ...INITIAL_SHELL_VIEW_STATE, runList: RUN_LIST },
      preferences: { locale: 'ko', theme: 'system', view: 'easy' },
      actions: ACTIONS,
      settingsOpen: false,
      onToggleSettings: () => undefined,
      onLocale: () => undefined,
      onTheme: () => undefined,
      onView: () => undefined,
      onCloseSettings: () => undefined,
    }),
  );
  assert.match(markup, /run-activity/);
  assert.match(markup, /data-run-source="canonical"/);
  assert.match(markup, /최근 작업/);
});
