import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  ConversationWorkspacePanel,
  INITIAL_SHELL_VIEW_STATE,
  ShellView,
  WorkspacePanel,
  type ShellActions,
} from '../src/renderer/app.js';
import type {
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
    { name: 'components', relativePath: 'src/components', kind: 'directory' },
    { name: 'index.ts', relativePath: 'src/index.ts', kind: 'file' },
    { name: 'linked', relativePath: 'src/linked', kind: 'link' },
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
      actions: ACTIONS,
      locale: 'en',
      advanced: false,
    }),
  );
  assert.match(markup, /Choose folder/);
  assert.match(markup, /Choose a folder to browse its files and subfolders safely/);
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
