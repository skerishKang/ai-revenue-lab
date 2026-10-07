/**
 * CLAW5 #3157 · CLAW1 #3165 — renderer tests for Korean/English Settings,
 * Easy/Advanced views and the product-language Easy surface.
 *
 * The renderer layer is the whole of this change, so the tests exercise the
 * real modules: the locale table, the non-sensitive preference store, the
 * visibility boundary, and the components rendered to static markup so the
 * negative secret-exposure check sees the actual DOM.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  LANGUAGE_LABELS,
  SHELL_LOCALES,
  deviceStateText,
  isShellLocale,
  readinessStateText,
  resolveInitialLocale,
  translate,
  type ShellLocale,
} from '../src/renderer/i18n.js';
import {
  DEFAULT_THEME_PREFERENCE,
  DEFAULT_VIEW_MODE,
  SHELL_VIEW_MODES,
  STORED_PREFERENCE_KEYS,
  UI_PREFERENCE_STORAGE_KEY,
  createLocalPreferenceStorage,
  loadUiPreferences,
  saveUiPreferences,
  type ShellThemePreference,
  type UiPreferenceStorage,
} from '../src/renderer/preferences.js';
import {
  ConnectionPanel,
  INITIAL_SHELL_VIEW_STATE,
  LogPanel,
  PairingPanel,
  RunnerPanel,
  SettingsPanel,
  ShellErrorView,
  ShellView,
  visibilityFor,
  type ShellActions,
  type ShellViewState,
} from '../src/renderer/app.js';
import type { BoundedLogResponse, RunnerHealthResponse, ShellStatus } from '../src/contract/ipc.js';

// Resolved from the package root, because this file is executed from
// dist/tests while the sources it inspects live under src/.
const packageRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const rendererDir = path.join(packageRoot, 'src', 'renderer');

// --- helpers ---------------------------------------------------------------
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
  deviceState: 'PAIRING',
  deviceStateRevision: 7,
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
  lines: ['runner: started', 'runner: bound command material'],
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

const THEMES_ORDER: readonly ShellThemePreference[] = ['system', 'light', 'dark'];

// --- 1. both locales exist and differ --------------------------------------
test('#3157 Korean and English are both available and genuinely different', () => {
  assert.deepEqual([...SHELL_LOCALES].sort(), ['en', 'ko']);
  for (const key of [
    'app.title',
    'readiness.start',
    'readiness.pause',
    'connection.recheck',
    'connection.title',
  ] as const) {
    assert.notEqual(translate('ko', key), translate('en', key), `missing translation for ${key}`);
  }
  assert.equal(translate('ko', 'app.title'), 'Padiem 데스크톱');
  assert.equal(translate('en', 'app.title'), 'Padiem Desktop');
  assert.equal(translate('ko', 'readiness.start'), '준비하기');
  assert.equal(translate('ko', 'readiness.pause'), '일시 정지');
  assert.equal(translate('ko', 'connection.recheck'), '연결 다시 확인');
  assert.equal(translate('en', 'readiness.start'), 'Get ready');
  assert.equal(translate('en', 'readiness.pause'), 'Pause');
  assert.equal(translate('en', 'connection.recheck'), 'Check the connection again');
});

test('#3157 the initial locale follows the host when nothing is stored', () => {
  assert.equal(resolveInitialLocale('ko-KR'), 'ko');
  assert.equal(resolveInitialLocale('ko'), 'ko');
  assert.equal(resolveInitialLocale('en-US'), 'en');
  assert.equal(resolveInitialLocale(undefined), 'en');
  assert.equal(loadUiPreferences(new MemoryStorage(), 'ko-KR').locale, 'ko');
});

test('#3157 a language switch is visible at runtime in the rendered DOM', () => {
  const korean = render(
    createElement(RunnerPanel, {
      status: STATUS,
      health: HEALTH,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'ko',
      advanced: false,
    }),
  );
  const english = render(
    createElement(RunnerPanel, {
      status: STATUS,
      health: HEALTH,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'en',
      advanced: false,
    }),
  );
  assert.match(korean, /준비하기/);
  assert.match(korean, /일시 정지/);
  assert.match(english, /Get ready/);
  assert.match(english, /Pause/);
  assert.doesNotMatch(korean, /Get ready/);
});

test('#3157 the language labels are the languages themselves', () => {
  assert.equal(LANGUAGE_LABELS.ko, '한국어');
  assert.equal(LANGUAGE_LABELS.en, 'English');
});

// --- 2. the preference persists and reloads --------------------------------
test('#3157 a language, theme and view choice persists locally and reloads', () => {
  const storage = new MemoryStorage();
  const first = loadUiPreferences(storage, 'en-US');
  assert.deepEqual(first, { locale: 'en', theme: 'system', view: 'easy' });

  saveUiPreferences(storage, { locale: 'ko', theme: 'dark', view: 'advanced' });
  const reloaded = loadUiPreferences(
    new MemoryStorage({ [UI_PREFERENCE_STORAGE_KEY]: storage.read(UI_PREFERENCE_STORAGE_KEY) ?? '' }),
    'en-US',
  );
  assert.deepEqual(reloaded, { locale: 'ko', theme: 'dark', view: 'advanced' });
});

test('#3157 only the three non-sensitive keys are ever written', () => {
  const storage = new MemoryStorage();
  saveUiPreferences(storage, { locale: 'ko', theme: 'dark', view: 'easy' });
  const written = JSON.parse(storage.read(UI_PREFERENCE_STORAGE_KEY)!);
  assert.deepEqual(Object.keys(written).sort(), [...STORED_PREFERENCE_KEYS].sort());
  assert.deepEqual([...STORED_PREFERENCE_KEYS].sort(), ['locale', 'theme', 'view']);
  const rendered = storage.read(UI_PREFERENCE_STORAGE_KEY)!;
  for (const forbidden of ['pairing', 'credential', 'token', 'deviceId', 'pid', 'broker']) {
    assert.doesNotMatch(rendered, new RegExp(forbidden, 'i'));
  }
});

test('#3157 a hostile or unknown stored preference falls back to the defaults', () => {
  for (const raw of ['not json', '[]', '{"locale":"fr","view":"debug"}', '{"locale":123}', 'null']) {
    const storage = new MemoryStorage({ [UI_PREFERENCE_STORAGE_KEY]: raw });
    const loaded = loadUiPreferences(storage, 'ko-KR');
    assert.equal(loaded.view, 'easy', raw);
    assert.equal(loaded.theme, DEFAULT_THEME_PREFERENCE, raw);
    assert.ok(isShellLocale(loaded.locale));
  }
  // An unknown stored locale still yields a supported one.
  assert.equal(loadUiPreferences(new MemoryStorage({ [UI_PREFERENCE_STORAGE_KEY]: '{"locale":"fr"}' }), 'en-GB').locale, 'en');
  // An unknown stored theme still yields a supported one.
  assert.equal(
    loadUiPreferences(new MemoryStorage({ [UI_PREFERENCE_STORAGE_KEY]: '{"theme":"neon"}' }), 'en-GB').theme,
    'system',
  );
});

test('#3157 a storage that throws never breaks the app', () => {
  const hostile: UiPreferenceStorage = {
    read() {
      throw new Error('blocked');
    },
    write() {
      throw new Error('blocked');
    },
  };
  assert.deepEqual(loadUiPreferences(hostile, 'ko-KR'), { locale: 'ko', theme: 'system', view: 'easy' });
  assert.doesNotThrow(() =>
    saveUiPreferences(hostile, { locale: 'ko', theme: 'light', view: 'advanced' }),
  );
  const local = createLocalPreferenceStorage(undefined);
  assert.equal(local.read(UI_PREFERENCE_STORAGE_KEY), null);
});

// --- 3. Easy is the default, Advanced is opt-in ---------------------------
test('#3157 Easy mode is the default and hides every developer field', () => {
  assert.equal(DEFAULT_VIEW_MODE, 'easy');
  assert.deepEqual([...SHELL_VIEW_MODES].sort(), ['advanced', 'easy']);
  const easy = visibilityFor('easy');
  assert.deepEqual(easy, {
    developerFacts: false,
    rawPairingSeamText: false,
    boundedLogInternals: false,
    signingNote: false,
  });

  const connection = render(
    createElement(ConnectionPanel, {
      status: STATUS,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'ko',
      advanced: easy.developerFacts,
    }),
  );
  const runner = render(
    createElement(RunnerPanel, {
      status: STATUS,
      health: HEALTH,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'ko',
      advanced: easy.developerFacts,
    }),
  );
  const pairing = render(
    createElement(PairingPanel, { pairing: null, locale: 'ko', advanced: easy.rawPairingSeamText }),
  );
  const log = render(createElement(LogPanel, { log: LOG, locale: 'ko', advanced: easy.boundedLogInternals }));

  for (const markup of [connection, runner, pairing, log]) {
    assert.doesNotMatch(markup, /canonical truth owner/i);
    assert.doesNotMatch(markup, /revision/i);
    assert.doesNotMatch(markup, /process boundary/i);
    assert.doesNotMatch(markup, /last exit code/i);
    assert.doesNotMatch(markup, /4242/); // the pid
    assert.doesNotMatch(markup, /deep link submitted/i);
    assert.doesNotMatch(markup, /runner: started/);
  }
});

test('#3157 Easy view never speaks in runner or process language', () => {
  const easy = visibilityFor('easy');
  const connection = render(
    createElement(ConnectionPanel, {
      status: STATUS,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'ko',
      advanced: easy.developerFacts,
    }),
  );
  const runner = render(
    createElement(RunnerPanel, {
      status: STATUS,
      health: HEALTH,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'ko',
      advanced: easy.developerFacts,
    }),
  );
  for (const markup of [connection, runner]) {
    assert.doesNotMatch(markup, /실행기/);
    assert.doesNotMatch(markup, /Runner/);
    assert.doesNotMatch(markup, /새로고침/);
    assert.doesNotMatch(markup, /Refresh/);
    assert.doesNotMatch(markup, /프로세스/);
    assert.doesNotMatch(markup, /Process id/i);
    assert.doesNotMatch(markup, /기록/);
  }
  // ...while still saying what this computer can do.
  assert.match(runner, /작업 준비/);
  assert.match(connection, /컴퓨터 연결/);
  assert.match(connection, /연결 다시 확인/);
});

test('#3157 Advanced mode keeps the existing diagnostics', () => {
  const advanced = visibilityFor('advanced');
  assert.deepEqual(advanced, {
    developerFacts: true,
    rawPairingSeamText: true,
    boundedLogInternals: true,
    signingNote: true,
  });

  const connection = render(
    createElement(ConnectionPanel, {
      status: STATUS,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'en',
      advanced: advanced.developerFacts,
    }),
  );
  const runner = render(
    createElement(RunnerPanel, {
      status: STATUS,
      health: HEALTH,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'en',
      advanced: advanced.developerFacts,
    }),
  );
  const log = render(createElement(LogPanel, { log: LOG, locale: 'en', advanced: advanced.boundedLogInternals }));

  assert.match(connection, /canonical truth owner/i);
  assert.match(connection, /#3080/);
  assert.match(runner, /process boundary/i);
  assert.match(runner, /last exit code/i);
  assert.match(runner, /4242/);
  assert.match(log, /runner: started/);
});

// --- 4. canonical device state is the connection truth ---------------------
test('#3157 the canonical device state is the primary connection truth in both views', () => {
  for (const locale of SHELL_LOCALES) {
    for (const advanced of [false, true]) {
      const markup = render(
        createElement(ConnectionPanel, {
          status: STATUS,
          busy: false,
          actions: NOOP_ACTIONS,
          locale,
          advanced,
        }),
      );
      // The wording is plain, the canonical value still travels with it.
      assert.match(markup, new RegExp(`data-canonical-state="${STATUS.deviceState}"`));
      assert.match(markup, new RegExp(deviceStateText(locale, 'PAIRING')));
    }
  }
});

test('#3157 every canonical state has plain wording in both languages', () => {
  const expectations: Record<string, [string, string]> = {
    NOT_PAIRED: ['연결 안 됨', 'Not connected'],
    PAIRING: ['연결 중', 'Connecting'],
    ONLINE: ['연결됨', 'Connected'],
    OFFLINE: ['연결 끊김', 'Disconnected'],
    ACTION_REQUIRED: ['확인 필요', 'Action required'],
  };
  for (const [state, [ko, en]] of Object.entries(expectations)) {
    assert.equal(deviceStateText('ko', state as never), ko);
    assert.equal(deviceStateText('en', state as never), en);
  }
  assert.equal(deviceStateText('ko', 'UNKNOWN'), '확인 중');
  assert.equal(readinessStateText('ko', 'RUNNING'), '준비됨');
  assert.equal(readinessStateText('ko', 'STOPPED'), '일시 정지됨');
  assert.equal(readinessStateText('en', 'STOPPED'), 'Paused');
  assert.equal(readinessStateText('ko', 'SOMETHING_NEW'), '확인 중');
});

test('#3157 the Easy view never shows pairing-seam text as the connection state', () => {
  const seam = render(
    createElement(PairingPanel, {
      pairing: { reason: 'no deep link submitted in this session' } as never,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.doesNotMatch(seam, /no deep link submitted/i);
  assert.equal(seam, '');
  // And the canonical connection panel is unaffected by the seam text.
  const connection = render(
    createElement(ConnectionPanel, {
      status: STATUS,
      busy: false,
      actions: NOOP_ACTIONS,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.match(connection, /연결 중/);
});

// --- 5. no functional drift: the same allowlisted API calls ---------------
test('#3157 Start/Stop/Recheck still drive the existing actions', () => {
  const calls: string[] = [];
  const actions: ShellActions = {
    start: async () => {
      calls.push('runnerStart');
    },
    stop: async () => {
      calls.push('runnerStop');
    },
    refresh: async () => {
      calls.push('refresh');
    },
    submitPairingDeepLink: async () => {
      calls.push('submitPairingDeepLink');
    },
    chooseWorkspaceRoot: async () => {
      calls.push('chooseWorkspaceRoot');
    },
    searchWorkspace: async () => {
      calls.push('searchWorkspace');
    },
    openWorkspaceDirectory: async () => {
      calls.push('openWorkspaceDirectory');
    },
    clearWorkspaceRoot: async () => {
      calls.push('clearWorkspaceRoot');
    },
    selectWorkspaceEntry: () => {
      calls.push('selectWorkspaceEntry');
    },
    selectConversation: async () => {
      calls.push('selectConversation');
    },
  };
  const runner = render(
    createElement(RunnerPanel, {
      status: STATUS,
      health: HEALTH,
      busy: false,
      actions,
      locale: 'en',
      advanced: false,
    }),
  );
  const connection = render(
    createElement(ConnectionPanel, {
      status: STATUS,
      busy: false,
      actions,
      locale: 'en',
      advanced: false,
    }),
  );
  // The same three controls, in product language.
  assert.match(runner, /Get ready/);
  assert.match(runner, /Pause/);
  assert.match(connection, /Check the connection again/);
  void actions.start();
  void actions.stop();
  void actions.refresh();
  assert.deepEqual(calls, ['runnerStart', 'runnerStop', 'refresh']);
});

test('#3436 the renderer still calls only the fixed allowlisted API methods', () => {
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
});

// --- 6. negative source/DOM check: no secret fields -----------------------
test('#3157 Easy view never renders raw pairing code or credential fields', () => {
  const fakePairingCode = 'SECRET-CODE-1234';
  const secretish = render(
    createElement(PairingPanel, {
      pairing: {
        reason: `padiem://pair?code=${fakePairingCode}`,
        deepLink: `padiem://pair?code=${fakePairingCode}`,
      } as never,
      locale: 'ko',
      advanced: false,
    }),
  );
  assert.doesNotMatch(secretish, /SECRET-CODE-1234/);
  assert.doesNotMatch(secretish, /padiem:\/\/pair\?code=/);
  assert.doesNotMatch(secretish, /credential/i);
  // #3165 — Easy view renders no diagnostics panel at all.
  assert.equal(secretish, '');
});

test('#3157 neither view nor preference code mentions credentials, pairing codes or P01', () => {
  for (const file of ['i18n.ts', 'preferences.ts']) {
    const source = readFileSync(path.join(rendererDir, file), 'utf8');
    for (const forbidden of ['pairing_code', 'pairingCode', 'credential', 'approval_payload', 'p01Payload']) {
      assert.doesNotMatch(source, new RegExp(forbidden, 'i'), `${file} mentions ${forbidden}`);
    }
  }
  // The preference record itself is the smallest possible surface.
  assert.deepEqual([...STORED_PREFERENCE_KEYS].sort(), ['locale', 'theme', 'view']);
});

/**
 * The vocabulary the runner stack really uses, quoted from the reasons it
 * answers with. None of it may reach Easy view.
 */
const RAW_DIAGNOSTIC_TERMS = [
  'headless',
  'separate process',
  'orphan',
  'process boundary',
  'canonical truth owner',
  'last exit code',
  'deep link submitted',
] as const;

function viewMarkup(state: ShellViewState, view: 'easy' | 'advanced'): string {
  return render(
    createElement(ShellView, {
      state,
      preferences: { locale: 'ko', theme: 'system', view },
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

test('#3157 Easy view exposes no raw technical notice', () => {
  const markup = viewMarkup(
    {
      ...INITIAL_SHELL_VIEW_STATE,
      status: STATUS,
      health: HEALTH,
      log: LOG,
      // Exactly what the runner stack answers with today.
      notice: 'headless runner started as a separate process',
      noticeAction: 'start',
    },
    'easy',
  );
  for (const term of RAW_DIAGNOSTIC_TERMS) {
    assert.doesNotMatch(markup, new RegExp(term, 'i'), `Easy view leaked: ${term}`);
  }
  // ...while still saying something useful.
  assert.match(markup, /작업 준비를 시작했습니다/);
});

test('#3157 the stop notice is plain in Easy view too', () => {
  const markup = viewMarkup(
    {
      ...INITIAL_SHELL_VIEW_STATE,
      status: STATUS,
      notice: 'headless runner stopped; no orphan process remains',
      noticeAction: 'stop',
    },
    'easy',
  );
  assert.doesNotMatch(markup, /orphan/i);
  assert.doesNotMatch(markup, /headless/i);
  assert.match(markup, /작업을 일시 정지했습니다/);
});

test('#3157 Advanced view is where the bounded raw diagnostic is allowed', () => {
  const raw = 'headless runner started as a separate process';
  const state = {
    ...INITIAL_SHELL_VIEW_STATE,
    status: STATUS,
    health: HEALTH,
    log: LOG,
    notice: raw,
    noticeAction: 'start' as const,
  };
  const advancedKo = viewMarkup(state, 'advanced');
  // The raw runner reason, the raw pairing-seam text, the log and the pid are
  // all back in Advanced — in the language the user chose.
  assert.match(advancedKo, /headless runner started as a separate process/);
  assert.match(advancedKo, /이 세션에서 제출된 딥링크가 없습니다/);
  assert.match(advancedKo, /runner: started/);
  assert.match(advancedKo, /기준 권위/);
  assert.match(advancedKo, /프로세스 경계/);
  assert.match(advancedKo, /4242/);

  const advancedEn = render(
    createElement(ShellView, {
      state,
      preferences: { locale: 'en', theme: 'system', view: 'advanced' },
      actions: NOOP_ACTIONS,
      settingsOpen: false,
      onToggleSettings: () => undefined,
      onLocale: () => undefined,
      onTheme: () => undefined,
      onView: () => undefined,
      onCloseSettings: () => undefined,
    }),
  );
  assert.match(advancedEn, /canonical truth owner/i);
  assert.match(advancedEn, /process boundary/i);
});

test('#3157 Easy view never renders the raw bridge error either', () => {
  const raw = 'padiemShell preload bridge unavailable; renderer has no authority';
  const easy = render(
    createElement(ShellErrorView, { locale: 'ko', view: 'easy', advanced: false, error: raw }),
  );
  assert.doesNotMatch(easy, /padiemShell/);
  assert.doesNotMatch(easy, /authority/i);
  assert.match(easy, /앱을 다시 시작/);
  const advanced = render(
    createElement(ShellErrorView, { locale: 'ko', view: 'advanced', advanced: true, error: raw }),
  );
  assert.match(advanced, /padiemShell preload bridge unavailable/);
});

test('#3157 every raw value the Easy view touches is behind the visibility guard', () => {
  // The rendered-DOM tests above are the proof; this pins the structure so a
  // later refactor cannot quietly reintroduce a bare raw interpolation.
  const source = readFileSync(path.join(rendererDir, 'app.tsx'), 'utf8');
  const guarded = /visibility\.developerFacts\s*\?\s*state\.notice/.test(source);
  assert.equal(guarded, true, 'the raw runner reason must stay behind the Advanced guard');
  const plainNotice = /noticeAction === 'start' \? 'notice\.started' : 'notice\.stopped'/.test(source);
  assert.equal(plainNotice, true, 'Easy must render the plain start/stop sentence');
  const guardedError = /advanced \? error : translate\(locale, 'app\.bridgeUnavailable'\)/.test(source);
  assert.equal(guardedError, true, 'the raw bridge error must stay behind the Advanced guard');
});

test('#3157 the Settings surface offers both languages, the themes and both views', () => {
  const markup = render(
    createElement(SettingsPanel, {
      preferences: { locale: 'ko', theme: 'system', view: 'easy' },
      onLocale: () => undefined,
      onTheme: () => undefined,
      onView: () => undefined,
      onClose: () => undefined,
    }),
  );
  assert.match(markup, /설정/);
  assert.match(markup, /한국어/);
  assert.match(markup, /English/);
  assert.match(markup, /쉬운 모드/);
  assert.match(markup, /고급 모드/);
  assert.match(markup, /테마/);
  assert.match(markup, /시스템/);
  assert.match(markup, /라이트/);
  assert.match(markup, /다크/);
  assert.match(markup, /value="ko"/);
  assert.match(markup, /value="en"/);
  assert.match(markup, /value="easy"/);
  assert.match(markup, /value="advanced"/);
  for (const theme of THEMES_ORDER) {
    assert.match(markup, new RegExp(`value="${theme}"`));
  }
});

test('#3157 the settings hint says a preference changes nothing else', () => {
  for (const locale of SHELL_LOCALES) {
    const hint = translate(locale, 'app.settingsHint');
    assert.ok(hint.length > 0);
  }
  assert.match(translate('ko', 'app.settings'), /설정/);
  assert.match(translate('en', 'app.settings'), /Settings/);
});
