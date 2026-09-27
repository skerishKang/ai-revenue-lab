/**
 * CLAW5 #3157 — renderer presentation strings for Korean and English.
 *
 * PRESENTATION ONLY. A locale is a vocabulary choice: it never changes the
 * canonical device state, the broker, the runner, pairing, P01 or any authority.
 * The canonical state value is always carried alongside its wording so the
 * translation can never become a second source of truth.
 */

import type { DeviceLifecycleState } from './types.js';

export const SHELL_LOCALES = ['ko', 'en'] as const;
export type ShellLocale = (typeof SHELL_LOCALES)[number];
export const DEFAULT_LOCALE: ShellLocale = 'en';

export function isShellLocale(value: unknown): value is ShellLocale {
  return typeof value === 'string' && (SHELL_LOCALES as readonly string[]).includes(value);
}

/**
 * Korean when the host asks for Korean, English otherwise.
 *
 * Only the *initial* value: once the user chooses a language in Settings, the
 * stored preference wins.
 */
export function resolveInitialLocale(hostLocale: unknown): ShellLocale {
  if (typeof hostLocale !== 'string') return DEFAULT_LOCALE;
  const tag = hostLocale.trim().toLowerCase();
  if (tag === '' ) return DEFAULT_LOCALE;
  return tag === 'ko' || tag.startsWith('ko-') ? 'ko' : 'en';
}

export type ShellStringKey =
  | 'app.title'
  | 'app.tagline'
  | 'app.settings'
  | 'app.settingsTitle'
  | 'app.settingsHint'
  | 'settings.language'
  | 'settings.view'
  | 'settings.viewEasy'
  | 'settings.viewAdvanced'
  | 'settings.close'
  | 'connection.title'
  | 'connection.heading'
  | 'connection.explainer'
  | 'connection.unknown'
  | 'runner.title'
  | 'runner.explainer'
  | 'runner.start'
  | 'runner.stop'
  | 'runner.refresh'
  | 'runner.state'
  | 'runner.stateUnknown'
  | 'runner.stateRunning'
  | 'runner.stateStarting'
  | 'runner.stateStopped'
  | 'runner.stateUnresponsive'
  | 'runner.pid'
  | 'runner.processBoundary'
  | 'runner.lastExitCode'
  | 'pairing.title'
  | 'pairing.body'
  | 'pairing.submitted'
  | 'pairing.idle'
  | 'log.title'
  | 'log.empty'
  | 'log.advancedOnly'
  | 'device.revision'
  | 'device.truthOwner'
  | 'notice.signing'
  | 'notice.started'
  | 'notice.stopped'
  | 'app.bridgeUnavailable'
  | 'language.ko'
  | 'language.en';

const KO: Record<ShellStringKey, string> = {
  'app.title': '파디엠 데스크톱',
  'app.tagline': '이 컴퓨터에서 파디엠 작업을 실행합니다.',
  'app.settings': '⚙ 설정',
  'app.settingsTitle': '설정',
  'app.settingsHint': '언어와 화면 모드만 변경됩니다. 연결이나 실행기 상태에는 영향이 없습니다.',
  'settings.language': '언어',
  'settings.view': '화면 모드',
  'settings.viewEasy': '쉬운 모드',
  'settings.viewAdvanced': '고급 모드',
  'settings.close': '닫기',
  'connection.title': '연결 상태',
  'connection.heading': '이 컴퓨터의 연결 상태',
  'connection.explainer': '파디엠 웹과 이 컴퓨터가 연결되어 있어야 작업을 실행할 수 있습니다.',
  'connection.unknown': '확인 중',
  'runner.title': '실행기',
  'runner.explainer': '실행기는 이 컴퓨터에서 작업을 대신 실행합니다. 시작해 두고 그대로 두면 됩니다.',
  'runner.start': '실행기 시작',
  'runner.stop': '실행기 중지',
  'runner.refresh': '새로고침',
  'runner.state': '실행기 상태',
  'runner.stateUnknown': '확인 중',
  'runner.stateRunning': '실행 중',
  'runner.stateStarting': '시작 중',
  'runner.stateStopped': '중지됨',
  'runner.stateUnresponsive': '응답 없음',
  'runner.pid': '프로세스 번호',
  'runner.processBoundary': '프로세스 경계',
  'runner.lastExitCode': '마지막 종료 코드',
  'pairing.title': '연결 방법',
  'pairing.body': '파디엠 웹에서 연결 요청을 보내면 이 컴퓨터가 자동으로 연결됩니다.',
  'pairing.submitted': '연결 요청을 받았습니다.',
  'pairing.idle': '이번 세션에서는 연결 요청이 없습니다.',
  'log.title': '실행기 기록',
  'log.empty': '아직 실행기 출력이 없습니다.',
  'log.advancedOnly': '실행 기록은 고급 모드에서 확인할 수 있습니다.',
  'device.revision': '리비전',
  'device.truthOwner': '기준 권위',
  'notice.signing': '이 버전은 내부용으로 빌드되었습니다.',
  'notice.started': '실행기를 시작했습니다.',
  'notice.stopped': '실행기를 중지했습니다.',
  'app.bridgeUnavailable': '지금 연결할 수 없습니다. 앱을 다시 시작한 뒤 시도해 주세요.',
  'language.ko': '한국어',
  'language.en': 'English',
};

const EN: Record<ShellStringKey, string> = {
  'app.title': 'Padiem Desktop',
  'app.tagline': 'Runs Padiem tasks on this computer.',
  'app.settings': '⚙ Settings',
  'app.settingsTitle': 'Settings',
  'app.settingsHint': 'Only the language and the view mode change here. Connections and the runner are untouched.',
  'settings.language': 'Language',
  'settings.view': 'View',
  'settings.viewEasy': 'Easy',
  'settings.viewAdvanced': 'Advanced',
  'settings.close': 'Close',
  'connection.title': 'Connection',
  'connection.heading': 'This computer’s connection',
  'connection.explainer': 'Padiem Web must be connected to this computer before tasks can run.',
  'connection.unknown': 'Checking…',
  'runner.title': 'Runner',
  'runner.explainer': 'The runner runs your tasks on this computer. Start it once and leave it running.',
  'runner.start': 'Start runner',
  'runner.stop': 'Stop runner',
  'runner.refresh': 'Refresh',
  'runner.state': 'Runner state',
  'runner.stateUnknown': 'Checking…',
  'runner.stateRunning': 'Running',
  'runner.stateStarting': 'Starting',
  'runner.stateStopped': 'Stopped',
  'runner.stateUnresponsive': 'Not responding',
  'runner.pid': 'Process id',
  'runner.processBoundary': 'Process boundary',
  'runner.lastExitCode': 'Last exit code',
  'pairing.title': 'How to connect',
  'pairing.body': 'Send a connection request from Padiem Web and this computer connects itself.',
  'pairing.submitted': 'A connection request was received.',
  'pairing.idle': 'No connection request in this session.',
  'log.title': 'Runner log',
  'log.empty': 'No runner output yet.',
  'log.advancedOnly': 'The runner log is available in Advanced view.',
  'device.revision': 'revision',
  'device.truthOwner': 'canonical truth owner',
  'notice.signing': 'This build is internal and unsigned.',
  'notice.started': 'The runner has been started.',
  'notice.stopped': 'The runner has been stopped.',
  'app.bridgeUnavailable': 'Padiem Desktop cannot connect right now. Restart the app and try again.',
  'language.ko': '한국어',
  'language.en': 'English',
};

export const SHELL_STRINGS: Readonly<Record<ShellLocale, Readonly<Record<ShellStringKey, string>>>> =
  Object.freeze({ ko: Object.freeze(KO), en: Object.freeze(EN) });

export function translate(locale: ShellLocale, key: ShellStringKey): string {
  const table = SHELL_STRINGS[locale] ?? SHELL_STRINGS[DEFAULT_LOCALE];
  return table[key] ?? SHELL_STRINGS[DEFAULT_LOCALE][key];
}

export const LANGUAGE_LABELS: Readonly<Record<ShellLocale, string>> = Object.freeze({
  ko: translate('ko', 'language.ko'),
  en: translate('en', 'language.en'),
});

/**
 * Plain-language wording for the canonical device state.
 *
 * The canonical value travels with the wording: the renderer reports what the
 * canonical authority decided, and only decides how to say it.
 */
const DEVICE_STATE_TEXT: Readonly<
  Record<ShellLocale, Readonly<Record<DeviceLifecycleState, string>>>
> = Object.freeze({
  ko: Object.freeze({
    NOT_PAIRED: '연결 안 됨',
    PAIRING: '연결 중',
    ONLINE: '연결됨',
    OFFLINE: '연결 끊김',
    ACTION_REQUIRED: '확인 필요',
  }),
  en: Object.freeze({
    NOT_PAIRED: 'Not connected',
    PAIRING: 'Connecting',
    ONLINE: 'Connected',
    OFFLINE: 'Disconnected',
    ACTION_REQUIRED: 'Action required',
  }),
});

export function deviceStateText(
  locale: ShellLocale,
  state: DeviceLifecycleState | 'UNKNOWN',
): string {
  if (state === 'UNKNOWN') return translate(locale, 'connection.unknown');
  const table = DEVICE_STATE_TEXT[locale] ?? DEVICE_STATE_TEXT[DEFAULT_LOCALE];
  return table[state] ?? state;
}

const RUNNER_STATE_TEXT: Readonly<Record<string, ShellStringKey>> = Object.freeze({
  RUNNING: 'runner.stateRunning',
  STARTING: 'runner.stateStarting',
  STOPPED: 'runner.stateStopped',
  UNRESPONSIVE: 'runner.stateUnresponsive',
  UNKNOWN: 'runner.stateUnknown',
});

export function runnerStateText(locale: ShellLocale, state: string | null | undefined): string {
  const key = RUNNER_STATE_TEXT[state ?? 'UNKNOWN'] ?? 'runner.stateUnknown';
  return translate(locale, key);
}

export const LOCALE_CHANGES_NO_AUTHORITY = true;
export const RENDERER_MAY_TRANSLATE_A_STATE = true;
export const RENDERER_MAY_DECLARE_A_STATE = false;
export const PRODUCTION_MUTATION = false;
