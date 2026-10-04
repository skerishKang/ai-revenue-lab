/**
 * CLAW5 #3157 · CLAW1 #3165 — renderer presentation strings for Korean and English.
 *
 * PRESENTATION ONLY. A locale is a vocabulary choice: it never changes the
 * canonical device state, the broker, the runner, pairing, P01 or any authority.
 * The canonical state value is always carried alongside its wording so the
 * translation can never become a second source of truth.
 *
 * #3165: Easy mode speaks in product language (computer connection, work
 * readiness, next action). The runner/process/log vocabulary is reserved for
 * Advanced diagnostics. Keys are named after the product concept, not the
 * implementation, so Easy copy cannot silently regress into jargon.
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
  if (tag === '') return DEFAULT_LOCALE;
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
  | 'settings.theme'
  | 'settings.themeSystem'
  | 'settings.themeLight'
  | 'settings.themeDark'
  | 'settings.close'
  | 'language.ko'
  | 'language.en'
  | 'connection.title'
  | 'connection.explainer'
  | 'connection.unknown'
  | 'connection.nextOnline'
  | 'connection.nextPairing'
  | 'connection.nextNotPaired'
  | 'connection.nextOffline'
  | 'connection.nextActionRequired'
  | 'connection.recheck'
  | 'readiness.title'
  | 'readiness.explainer'
  | 'readiness.stateReady'
  | 'readiness.stateStarting'
  | 'readiness.statePaused'
  | 'readiness.stateAttention'
  | 'readiness.stateChecking'
  | 'readiness.bodyReady'
  | 'readiness.bodyStarting'
  | 'readiness.bodyPaused'
  | 'readiness.bodyAttention'
  | 'readiness.bodyChecking'
  | 'readiness.start'
  | 'readiness.pause'
  | 'readiness.pid'
  | 'readiness.processBoundary'
  | 'readiness.processBoundaryValue'
  | 'readiness.lastExitCode'
  | 'device.revision'
  | 'device.truthOwner'
  | 'workspace.title'
  | 'workspace.explainer'
  | 'workspace.choose'
  | 'workspace.change'
  | 'workspace.clear'
  | 'workspace.empty'
  | 'workspace.up'
  | 'workspace.root'
  | 'workspace.unavailable'
  | 'workspace.noEntries'
  | 'workspace.truncated'
  | 'desktop.conversationTitle'
  | 'desktop.conversationPendingTitle'
  | 'desktop.conversationPendingBody'
  | 'desktop.conversationAuthorityNote'
  | 'desktop.conversationListLabel'
  | 'desktop.conversationUntitled'
  | 'desktop.conversationSelectHint'
  | 'desktop.runTitle'
  | 'desktop.runPendingTitle'
  | 'desktop.runPendingBody'
  | 'desktop.runEmpty'
  | 'desktop.runStatusQueued'
  | 'desktop.runStatusPreparing'
  | 'desktop.runStatusRunning'
  | 'desktop.runStatusWaitingApproval'
  | 'desktop.runStatusCompleted'
  | 'desktop.runStatusFailed'
  | 'desktop.runStatusCancelled'
  | 'desktop.runArtifact'
  | 'desktop.runConversationLinked'
  | 'desktop.runAuthorityNote'
  | 'desktop.runIdLabel'
  | 'desktop.runConversationLabel'
  | 'desktop.runWorkspaceLabel'
  | 'desktop.runChannelLabel'
  | 'desktop.localTitle'
  | 'diagnostics.title'
  | 'diagnostics.body'
  | 'diagnostics.seamIdle'
  | 'log.title'
  | 'log.empty'
  | 'notice.signing'
  | 'notice.started'
  | 'notice.stopped'
  | 'app.bridgeUnavailable';

const KO: Record<ShellStringKey, string> = {
  'app.title': 'Padiem 데스크톱',
  'app.tagline': '이 컴퓨터에서 Padiem 작업을 실행합니다.',
  'app.settings': '설정',
  'app.settingsTitle': '설정',
  'app.settingsHint': '언어, 테마, 화면 모드만 바뀝니다. 컴퓨터 연결과 작업 준비 상태는 그대로입니다.',
  'settings.language': '언어',
  'settings.view': '화면 모드',
  'settings.viewEasy': '쉬운 모드',
  'settings.viewAdvanced': '고급 모드',
  'settings.theme': '테마',
  'settings.themeSystem': '시스템',
  'settings.themeLight': '라이트',
  'settings.themeDark': '다크',
  'settings.close': '닫기',
  'language.ko': '한국어',
  'language.en': 'English',
  'connection.title': '컴퓨터 연결',
  'connection.explainer': 'Padiem 웹과 이 컴퓨터가 연결되어 있어야 작업을 맡길 수 있습니다.',
  'connection.unknown': '확인 중',
  'connection.nextOnline': '이 컴퓨터에서 바로 작업을 맡길 수 있습니다.',
  'connection.nextPairing': '연결을 확인하는 중입니다. 잠시만 기다려 주세요.',
  'connection.nextNotPaired': 'Padiem 웹에서 이 컴퓨터 연결을 눌러 주세요.',
  'connection.nextOffline': 'Padiem 웹에서 이 컴퓨터를 다시 연결해 주세요.',
  'connection.nextActionRequired': '연결 다시 확인을 눌러 상태를 확인해 주세요.',
  'connection.recheck': '연결 다시 확인',
  'readiness.title': '작업 준비',
  'readiness.explainer': '이 컴퓨터가 작업을 실행할 준비가 되었는지 보여줍니다.',
  'readiness.stateReady': '준비됨',
  'readiness.stateStarting': '준비 중',
  'readiness.statePaused': '일시 정지됨',
  'readiness.stateAttention': '확인 필요',
  'readiness.stateChecking': '확인 중',
  'readiness.bodyReady': '이 컴퓨터가 작업을 실행할 수 있습니다.',
  'readiness.bodyStarting': '곧 작업을 맡길 수 있습니다.',
  'readiness.bodyPaused': '작업을 실행하려면 준비하기를 눌러 주세요.',
  'readiness.bodyAttention': '연결 다시 확인 후 다시 시도해 주세요.',
  'readiness.bodyChecking': '준비 상태를 확인하는 중입니다.',
  'readiness.start': '준비하기',
  'readiness.pause': '일시 정지',
  'readiness.pid': '프로세스 번호',
  'readiness.processBoundary': '프로세스 경계',
  'readiness.processBoundaryValue': '별도 헤드리스 프로세스입니다. 화면은 실행 권위가 아닙니다.',
  'readiness.lastExitCode': '마지막 종료 코드',
  'device.revision': '리비전',
  'device.truthOwner': '기준 권위',
  'workspace.title': '작업 폴더',
  'workspace.explainer': '이 컴퓨터에서 Padiem이 작업할 프로젝트 폴더를 선택합니다.',
  'workspace.choose': '폴더 선택',
  'workspace.change': '폴더 변경',
  'workspace.clear': '선택 해제',
  'workspace.empty': '폴더를 선택하면 파일과 하위 폴더를 안전하게 탐색할 수 있습니다.',
  'workspace.up': '상위 폴더',
  'workspace.root': '처음으로',
  'workspace.unavailable': '이 폴더를 지금 열 수 없습니다.',
  'workspace.noEntries': '이 폴더는 비어 있습니다.',
  'workspace.truncated': '항목이 많아 일부만 표시했습니다.',
  'desktop.conversationTitle': 'Claw',
  'desktop.conversationPendingTitle': '같은 대화를 데스크톱에서 이어서 여는 연결을 준비 중입니다.',
  'desktop.conversationPendingBody': '이 화면은 새 대화를 만들지 않습니다. Padiem Web의 기존 대화를 그대로 가져오는 연결이 확인되면 여기에서 이어집니다.',
  'desktop.conversationAuthorityNote': '기존 Padiem Chat/Claw 대화가 기준입니다. Desktop은 별도 대화를 만들지 않습니다.',
  'desktop.conversationListLabel': '기존 대화',
  'desktop.conversationUntitled': '제목 없는 대화',
  'desktop.conversationSelectHint': '왼쪽에서 이어볼 대화를 선택하면 기존 대화가 그대로 표시됩니다.',
  'desktop.runTitle': '최근 작업',
  'desktop.runPendingTitle': '작업 기록 연결을 준비 중입니다.',
  'desktop.runPendingBody': 'Padiem Web에서 맡긴 작업과 결과를 그대로 보여드리기 위해 연결을 확인하는 중입니다. 이 화면은 새 작업을 만들지 않습니다.',
  'desktop.runEmpty': '아직 표시할 작업이 없습니다.',
  'desktop.runStatusQueued': '대기 중',
  'desktop.runStatusPreparing': '준비 중',
  'desktop.runStatusRunning': '실행 중',
  'desktop.runStatusWaitingApproval': '승인 대기',
  'desktop.runStatusCompleted': '완료',
  'desktop.runStatusFailed': '실패',
  'desktop.runStatusCancelled': '취소됨',
  'desktop.runArtifact': '결과 파일 있음',
  'desktop.runConversationLinked': '대화 연결',
  'desktop.runAuthorityNote': '작업 기록은 Padiem Claw 기준 권위가 제공합니다. Desktop은 별도 작업 기록을 만들지 않으며 실시간 표시가 아닌 최근 기록 조회입니다.',
  'desktop.runIdLabel': '실행 ID',
  'desktop.runConversationLabel': '대화 ID',
  'desktop.runWorkspaceLabel': '워크스페이스 ID',
  'desktop.runChannelLabel': '채널',
  'desktop.localTitle': '이 컴퓨터',
  'diagnostics.title': '연결 진단',
  'diagnostics.body': 'Padiem 웹에서 연결 요청을 보내면 이 컴퓨터가 자동으로 연결됩니다.',
  'diagnostics.seamIdle': '이 세션에서 제출된 딥링크가 없습니다.',
  'log.title': '실행 기록',
  'log.empty': '아직 기록이 없습니다.',
  'notice.signing': '이 빌드는 내부용이며 서명되지 않았습니다.',
  'notice.started': '작업 준비를 시작했습니다.',
  'notice.stopped': '작업을 일시 정지했습니다.',
  'app.bridgeUnavailable': 'Padiem 데스크톱이 지금 연결할 수 없습니다. 앱을 다시 시작해 주세요.',
};

const EN: Record<ShellStringKey, string> = {
  'app.title': 'Padiem Desktop',
  'app.tagline': 'Runs Padiem tasks on this computer.',
  'app.settings': 'Settings',
  'app.settingsTitle': 'Settings',
  'app.settingsHint': 'Only the language, theme and view change here. The computer connection and work readiness stay the same.',
  'settings.language': 'Language',
  'settings.view': 'View',
  'settings.viewEasy': 'Easy',
  'settings.viewAdvanced': 'Advanced',
  'settings.theme': 'Theme',
  'settings.themeSystem': 'System',
  'settings.themeLight': 'Light',
  'settings.themeDark': 'Dark',
  'settings.close': 'Close',
  'language.ko': '한국어',
  'language.en': 'English',
  'connection.title': 'Computer connection',
  'connection.explainer': 'Padiem Web must be connected to this computer before you can hand over work.',
  'connection.unknown': 'Checking…',
  'connection.nextOnline': 'You can hand work to this computer right away.',
  'connection.nextPairing': 'Checking the connection. This only takes a moment.',
  'connection.nextNotPaired': "Press 'Connect this computer' in Padiem Web.",
  'connection.nextOffline': 'Reconnect this computer from Padiem Web.',
  'connection.nextActionRequired': "Press 'Check the connection again' to refresh the status.",
  'connection.recheck': 'Check the connection again',
  'readiness.title': 'Work readiness',
  'readiness.explainer': 'Shows whether this computer is ready to run your work.',
  'readiness.stateReady': 'Ready',
  'readiness.stateStarting': 'Getting ready',
  'readiness.statePaused': 'Paused',
  'readiness.stateAttention': 'Needs attention',
  'readiness.stateChecking': 'Checking…',
  'readiness.bodyReady': 'This computer can run your work.',
  'readiness.bodyStarting': 'You will be able to hand over work shortly.',
  'readiness.bodyPaused': "Press 'Get ready' to let this computer run work.",
  'readiness.bodyAttention': 'Check the connection again, then retry.',
  'readiness.bodyChecking': 'Checking the readiness status.',
  'readiness.start': 'Get ready',
  'readiness.pause': 'Pause',
  'readiness.pid': 'Process id',
  'readiness.processBoundary': 'Process boundary',
  'readiness.processBoundaryValue': 'separate headless process (renderer is not the execution authority)',
  'readiness.lastExitCode': 'Last exit code',
  'device.revision': 'revision',
  'device.truthOwner': 'canonical truth owner',
  'workspace.title': 'Work folder',
  'workspace.explainer': 'Choose the project folder Padiem may work with on this computer.',
  'workspace.choose': 'Choose folder',
  'workspace.change': 'Change folder',
  'workspace.clear': 'Clear',
  'workspace.empty': 'Choose a folder to browse its files and subfolders safely.',
  'workspace.up': 'Up',
  'workspace.root': 'Root',
  'workspace.unavailable': 'This folder cannot be opened right now.',
  'workspace.noEntries': 'This folder is empty.',
  'workspace.truncated': 'Only the first items are shown.',
  'desktop.conversationTitle': 'Claw',
  'desktop.conversationPendingTitle': 'Same-conversation continuity is being prepared for Desktop.',
  'desktop.conversationPendingBody': 'This surface does not create another conversation. It will continue the existing Padiem Web conversation once the canonical projection is connected.',
  'desktop.conversationAuthorityNote': 'The existing Padiem Chat/Claw conversation remains canonical. Desktop does not create another conversation.',
  'desktop.conversationListLabel': 'Existing conversations',
  'desktop.conversationUntitled': 'Untitled conversation',
  'desktop.conversationSelectHint': 'Pick a conversation on the left to see the same existing conversation here.',
  'desktop.runTitle': 'Recent runs',
  'desktop.runPendingTitle': 'Run history connection is being prepared.',
  'desktop.runPendingBody': 'Runs and results you started in Padiem Web will appear here exactly as they are. This surface does not create new runs.',
  'desktop.runEmpty': 'No runs to show yet.',
  'desktop.runStatusQueued': 'Queued',
  'desktop.runStatusPreparing': 'Preparing',
  'desktop.runStatusRunning': 'Running',
  'desktop.runStatusWaitingApproval': 'Waiting for approval',
  'desktop.runStatusCompleted': 'Completed',
  'desktop.runStatusFailed': 'Failed',
  'desktop.runStatusCancelled': 'Cancelled',
  'desktop.runArtifact': 'Has result file',
  'desktop.runConversationLinked': 'Linked conversation',
  'desktop.runAuthorityNote': 'Run history is provided by the canonical Padiem Claw authority. Desktop keeps no separate run history, and this is a recent-records view, not a live feed.',
  'desktop.runIdLabel': 'Run ID',
  'desktop.runConversationLabel': 'Conversation ID',
  'desktop.runWorkspaceLabel': 'Workspace ID',
  'desktop.runChannelLabel': 'Channel',
  'desktop.localTitle': 'This computer',
  'diagnostics.title': 'Connection diagnostics',
  'diagnostics.body': 'Send a connection request from Padiem Web and this computer connects itself.',
  'diagnostics.seamIdle': 'No deep link submitted in this session.',
  'log.title': 'Runner log',
  'log.empty': 'No runner output yet.',
  'notice.signing': 'This build is internal and unsigned.',
  'notice.started': 'Getting this computer ready to run work.',
  'notice.stopped': 'Work has been paused.',
  'app.bridgeUnavailable': 'Padiem Desktop cannot connect right now. Restart the app and try again.',
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

/**
 * The one plain sentence that tells a normal user what happens next for the
 * current computer-connection state. #3165 Easy mode guidance.
 */
const CONNECTION_NEXT_ACTION_TEXT: Readonly<
  Record<ShellLocale, Readonly<Record<DeviceLifecycleState | 'UNKNOWN', string>>>
> = Object.freeze({
  ko: Object.freeze({
    NOT_PAIRED: translate('ko', 'connection.nextNotPaired'),
    PAIRING: translate('ko', 'connection.nextPairing'),
    ONLINE: translate('ko', 'connection.nextOnline'),
    OFFLINE: translate('ko', 'connection.nextOffline'),
    ACTION_REQUIRED: translate('ko', 'connection.nextActionRequired'),
    UNKNOWN: translate('ko', 'connection.nextPairing'),
  }),
  en: Object.freeze({
    NOT_PAIRED: translate('en', 'connection.nextNotPaired'),
    PAIRING: translate('en', 'connection.nextPairing'),
    ONLINE: translate('en', 'connection.nextOnline'),
    OFFLINE: translate('en', 'connection.nextOffline'),
    ACTION_REQUIRED: translate('en', 'connection.nextActionRequired'),
    UNKNOWN: translate('en', 'connection.nextPairing'),
  }),
});

export function connectionNextActionText(
  locale: ShellLocale,
  state: DeviceLifecycleState | 'UNKNOWN',
): string {
  const table = CONNECTION_NEXT_ACTION_TEXT[locale] ?? CONNECTION_NEXT_ACTION_TEXT[DEFAULT_LOCALE];
  return table[state] ?? table.UNKNOWN;
}

/**
 * Product wording for the runner's local health.
 *
 * RUNNING is what the user experiences as "ready"; the canonical health value
 * is still carried next to the wording (data-canonical-state) for support.
 */
const READINESS_STATE_TEXT: Readonly<Record<string, ShellStringKey>> = Object.freeze({
  RUNNING: 'readiness.stateReady',
  STARTING: 'readiness.stateStarting',
  STOPPED: 'readiness.statePaused',
  UNRESPONSIVE: 'readiness.stateAttention',
  UNKNOWN: 'readiness.stateChecking',
});

export function readinessStateText(locale: ShellLocale, state: string | null | undefined): string {
  const key = READINESS_STATE_TEXT[state ?? 'UNKNOWN'] ?? 'readiness.stateChecking';
  return translate(locale, key);
}

/** The one plain sentence for the current readiness state. #3165 Easy mode. */
const READINESS_BODY_TEXT: Readonly<Record<string, ShellStringKey>> = Object.freeze({
  RUNNING: 'readiness.bodyReady',
  STARTING: 'readiness.bodyStarting',
  STOPPED: 'readiness.bodyPaused',
  UNRESPONSIVE: 'readiness.bodyAttention',
  UNKNOWN: 'readiness.bodyChecking',
});

export function readinessBodyText(locale: ShellLocale, state: string | null | undefined): string {
  const key = READINESS_BODY_TEXT[state ?? 'UNKNOWN'] ?? 'readiness.bodyChecking';
  return translate(locale, key);
}

export const LOCALE_CHANGES_NO_AUTHORITY = true;
export const RENDERER_MAY_TRANSLATE_A_STATE = true;
export const RENDERER_MAY_DECLARE_A_STATE = false;
export const PRESENTATION_ONLY = true;
export const PRODUCTION_MUTATION = false;
