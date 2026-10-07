/**
 * CLAW1 #3165 — renderer tests for the Easy-mode UX pass.
 *
 * Covers the three things #3165 changes on the renderer:
 *   - the theme preference (System / Light / Dark) and its document application
 *   - the product-language Easy surface (no runner/process/log vocabulary)
 *   - the Advanced diagnostics that must survive the pass unchanged
 *
 * Runs against the real modules, rendered to static markup, so the assertions
 * see the DOM the user would see (minus hydration).
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  connectionNextActionText,
  readinessBodyText,
  translate,
} from '../src/renderer/i18n.js';
import {
  DEFAULT_THEME_PREFERENCE,
  SHELL_THEME_PREFERENCES,
  STORED_PREFERENCE_KEYS,
  UI_PREFERENCE_STORAGE_KEY,
  isShellThemePreference,
  loadUiPreferences,
  resolveTheme,
  saveUiPreferences,
  type ShellThemePreference,
  type UiPreferenceStorage,
} from '../src/renderer/preferences.js';
import {
  INITIAL_SHELL_VIEW_STATE,
  applyDocumentAppearance,
  ShellView,
  type ShellActions,
  type ShellViewState,
} from '../src/renderer/app.js';
import type { BoundedLogResponse, RunnerHealthResponse, ShellStatus } from '../src/contract/ipc.js';

class MemoryStorage implements UiPreferenceStorage {
  readonly written = new Map<string, string>();
  constructor(private readonly seed: Record<string, string> = {}) {}
  read(key: string): string | null {
    return this.written.get(key) ?? this.seed[key] ?? null;
  }
  write(key: string, value: string): void {
    this.written.set(key, value);
  }
}

const STATUS: ShellStatus = {
  deviceState: 'ONLINE',
  deviceStateRevision: 3,
  authoritativeTruthOwner: '#3080',
  runnerState: 'RUNNING',
  runnerPid: 4242,
} as ShellStatus;

const HEALTH: RunnerHealthResponse = {
  state: 'RUNNING',
  pid: 4242,
  lastExitCode: 0,
} as RunnerHealthResponse;

const LOG: BoundedLogResponse = {
  lines: ['runner: started'],
  truncated: false,
  redactionApplied: true,
} as BoundedLogResponse;

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

function render(element: ReactElement | null): string {
  return element === null ? '' : renderToStaticMarkup(element);
}

function shellMarkup(
  view: 'easy' | 'advanced',
  locale: 'ko' | 'en',
  theme: ShellThemePreference = 'system',
): string {
  const state: ShellViewState = {
    ...INITIAL_SHELL_VIEW_STATE,
    status: STATUS,
    health: HEALTH,
    log: LOG,
  };
  return render(
    createElement(ShellView, {
      state,
      preferences: { locale, theme, view },
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

// --- 1. theme preference ----------------------------------------------------
test('#3165 the theme preference offers System, Light and Dark with System as default', () => {
  assert.deepEqual([...SHELL_THEME_PREFERENCES], ['system', 'light', 'dark']);
  assert.equal(DEFAULT_THEME_PREFERENCE, 'system');
  assert.equal(isShellThemePreference('system'), true);
  assert.equal(isShellThemePreference('light'), true);
  assert.equal(isShellThemePreference('dark'), true);
  assert.equal(isShellThemePreference('neon'), false);
  assert.equal(isShellThemePreference(7), false);
});

test('#3165 System follows the OS; an explicit theme always wins', () => {
  assert.equal(resolveTheme('system', true), 'dark');
  assert.equal(resolveTheme('system', false), 'light');
  assert.equal(resolveTheme('light', true), 'light');
  assert.equal(resolveTheme('dark', false), 'dark');
});

test('#3165 a stored theme round-trips and unknown values fall back to System', () => {
  const storage = new MemoryStorage();
  saveUiPreferences(storage, { locale: 'ko', theme: 'dark', view: 'advanced' });
  const written = JSON.parse(storage.read(UI_PREFERENCE_STORAGE_KEY)!);
  assert.deepEqual(Object.keys(written).sort(), [...STORED_PREFERENCE_KEYS].sort());
  assert.equal(written.theme, 'dark');

  const reloaded = loadUiPreferences(
    new MemoryStorage({ [UI_PREFERENCE_STORAGE_KEY]: storage.read(UI_PREFERENCE_STORAGE_KEY) ?? '' }),
    'en-US',
  );
  assert.equal(reloaded.theme, 'dark');

  for (const raw of ['{"theme":"neon"}', '{"theme":5}', '{"theme":null}']) {
    const loaded = loadUiPreferences(new MemoryStorage({ [UI_PREFERENCE_STORAGE_KEY]: raw }), 'en-US');
    assert.equal(loaded.theme, 'system', raw);
  }
});

test('#3165 applyDocumentAppearance sets only the theme and language tags', () => {
  const dataset: { [key: string]: string | undefined } = {};
  const target = { documentElement: { dataset, lang: 'en' } };
  applyDocumentAppearance(target, 'dark', 'ko');
  assert.equal(target.documentElement.dataset['theme'], 'dark');
  assert.equal(target.documentElement.lang, 'ko');
  assert.deepEqual(Object.keys(dataset), ['theme']);

  applyDocumentAppearance(target, 'light', 'en');
  assert.equal(target.documentElement.dataset['theme'], 'light');
  assert.equal(target.documentElement.lang, 'en');
});

// --- 2. the Easy surface speaks product language ----------------------------
test('#3165 Easy view shows product language in Korean', () => {
  const markup = shellMarkup('easy', 'ko');
  assert.match(markup, /컴퓨터 연결/);
  assert.match(markup, /연결 다시 확인/);
  assert.match(markup, /작업 준비/);
  assert.match(markup, /준비하기/);
  assert.match(markup, /일시 정지/);
  assert.match(markup, /설정/);
  for (const banned of [
    '실행기',
    '새로고침',
    '프로세스',
    '실행 기록',
    '헤드리스',
    '딥링크',
    'Runner',
    'Refresh',
    'headless',
    'deep link',
  ]) {
    assert.doesNotMatch(markup, new RegExp(banned), `Easy view leaked: ${banned}`);
  }
  assert.doesNotMatch(markup, /\blog\b/i);
});

test('#3165 Easy view shows product language in English', () => {
  const markup = shellMarkup('easy', 'en');
  assert.match(markup, /Computer connection/);
  assert.match(markup, /Check the connection again/);
  assert.match(markup, /Work readiness/);
  assert.match(markup, /Get ready/);
  assert.match(markup, /Pause/);
  for (const banned of ['Runner', 'Refresh', 'Process id', 'Runner log', 'headless']) {
    assert.doesNotMatch(markup, new RegExp(banned), `Easy view leaked: ${banned}`);
  }
});

test('#3165 Easy view renders no log panel and no connection diagnostics panel', () => {
  const markup = shellMarkup('easy', 'ko');
  assert.doesNotMatch(markup, /실행 기록/);
  assert.doesNotMatch(markup, /연결 진단/);
});

test('#3165 Advanced view keeps the diagnostics after the pass', () => {
  const markup = shellMarkup('advanced', 'ko');
  assert.match(markup, /연결 진단/);
  assert.match(markup, /프로세스 경계/);
  assert.match(markup, /리비전/);
  assert.match(markup, /실행 기록/);
  assert.match(markup, /서명되지 않았습니다/);
  assert.match(markup, /4242/);
});

// --- 3. next-action guidance ------------------------------------------------
test('#3165 the connection card gives one plain next action per state', () => {
  assert.equal(connectionNextActionText('ko', 'ONLINE'), '이 컴퓨터에서 바로 작업을 맡길 수 있습니다.');
  assert.equal(connectionNextActionText('en', 'ONLINE'), 'You can hand work to this computer right away.');
  assert.equal(connectionNextActionText('ko', 'NOT_PAIRED'), 'Padiem 웹에서 이 컴퓨터 연결을 눌러 주세요.');
  assert.equal(
    connectionNextActionText('en', 'ACTION_REQUIRED'),
    "Press 'Check the connection again' to refresh the status.",
  );
  assert.equal(
    connectionNextActionText('ko', 'UNKNOWN'),
    '연결을 확인하는 중입니다. 잠시만 기다려 주세요.',
  );
  // Every canonical state and the unknown fallback return a non-empty sentence.
  for (const state of ['NOT_PAIRED', 'PAIRING', 'ONLINE', 'OFFLINE', 'ACTION_REQUIRED', 'UNKNOWN'] as const) {
    for (const locale of ['ko', 'en'] as const) {
      assert.ok(connectionNextActionText(locale, state).length > 0, `${locale}/${state}`);
    }
  }
});

test('#3165 the readiness card explains each state in plain words', () => {
  assert.equal(readinessBodyText('ko', 'RUNNING'), '이 컴퓨터가 작업을 실행할 수 있습니다.');
  assert.equal(readinessBodyText('en', 'STOPPED'), "Press 'Get ready' to let this computer run work.");
  assert.equal(readinessBodyText('ko', 'UNRESPONSIVE'), '연결 다시 확인 후 다시 시도해 주세요.');
  assert.equal(readinessBodyText('ko', 'SOMETHING_NEW'), '준비 상태를 확인하는 중입니다.');
  for (const state of ['RUNNING', 'STARTING', 'STOPPED', 'UNRESPONSIVE', 'UNKNOWN'] as const) {
    for (const locale of ['ko', 'en'] as const) {
      assert.ok(readinessBodyText(locale, state).length > 0, `${locale}/${state}`);
    }
  }
});

// --- 4. previously hardcoded diagnostics are localized ----------------------
test('#3165 the diagnostics that used to be hardcoded English are localized', () => {
  for (const key of ['readiness.processBoundaryValue', 'diagnostics.seamIdle'] as const) {
    const ko = translate('ko', key);
    const en = translate('en', key);
    assert.ok(ko.length > 0 && en.length > 0);
    assert.notEqual(ko, en, `missing translation for ${key}`);
  }
  // The old hardcoded value must no longer appear in Easy markup at all.
  assert.doesNotMatch(shellMarkup('easy', 'en'), /separate headless process/i);
  // ...and the Advanced view shows the localized value in the chosen language.
  assert.match(shellMarkup('advanced', 'ko'), /별도 헤드리스 프로세스입니다\. 화면은 실행 권위가 아닙니다\./);
});
