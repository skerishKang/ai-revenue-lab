import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
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
