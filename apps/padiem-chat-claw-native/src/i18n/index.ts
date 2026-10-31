/**
 * Korean-first copy for the native app. The Web client is Korean-first and
 * keeps English fallbacks inline; the same order is preserved here.
 */

export const ko = {
  appName: 'PADIEM',
  chatTab: 'Chat',
  clawTab: 'Claw',
  historyTab: '기록',
  settingsTab: '설정',

  signInTitle: 'PADIEM 로그인',
  signInSubtitle: 'Google 계정으로 로그인하고 AI 도우미를 시작하세요.',
  signInWithGoogle: 'Google로 로그인',
  signInWithPassword: '이메일·아이디로 로그인',
  identifierLabel: '이메일 또는 아이디',
  passwordLabel: '비밀번호',
  signIn: '로그인',
  signOut: '로그아웃',
  signingIn: '로그인 중…',

  handoffTitle: '브라우저에서 로그인',
  handoffInstructions:
    '브라우저에서 Google 계정으로 로그인한 뒤, 아래 코드를 입력해 주세요.',
  handoffCodeLabel: '8자리 로그인 코드',
  handoffStatus: '로그인 확인 중…',
  handoffPending: '브라우저에서 로그인을 완료해 주세요.',
  handoffReady: '확인되었습니다. 앱으로 돌아오는 중…',
  handoffConfirm: '코드 확인',
  handoffExpired: '로그인 시간이 만료되었습니다. 다시 시도해 주세요.',

  newConversation: '새 대화',
  recentConversations: '최근 대화',
  searchConversations: '대화 검색',
  noConversations: '저장된 대화가 없습니다.',
  deleteConversation: '대화 삭제',
  deleteConversationConfirm: '이 대화를 삭제할까요?',

  messageInputPlaceholder: '메시지를 입력하세요',
  send: '전송',
  stop: '중지',
  attach: '파일 첨부',
  mic: '음성 입력',
  voiceMode: '음성 대화',

  modelLabel: 'AI 등급',
  modelUnavailable: '사용할 수 없는 등급',
  modelSaveFailed: '등급을 저장하지 못했습니다.',

  voiceM1: '받아쓰기 후 직접 전송',
  voiceM2: '발화 종료 후 문자 답변',
  voiceM3: '문자·음성 답변',
  voiceM4: '음성 통화형 화면',
  voiceListening: '듣는 중…',
  voiceThinking: '생각 중…',
  voiceSpeaking: '말하는 중…',
  voiceUnavailable: '음성 기능을 현재 사용할 수 없습니다.',
  voiceSpeak: '읽어주기',

  clawConnected: 'PC 연결됨',
  clawDisconnected: 'PC 연결 안 됨',
  clawConnect: 'PC 연결',
  clawRefresh: '연결 새로고침',
  clawRun: '작업 실행',
  clawRunning: '작업 실행 중…',
  clawApprove: '승인',
  clawReject: '거절',
  clawRuns: '최근 작업',
  clawNoRuns: '실행된 작업이 없습니다.',
  clawDevice: '연결된 PC',
  clawNoDevice: '연결된 PC가 없습니다.',

  settingsTitle: '설정',
  apiBaseUrl: '서버 주소',
  language: '언어',
  member: '회원 등급',
  account: '계정',
  signedInAs: '로그인 계정',
  guest: '로그인 필요',

  errorTitle: '오류',
  retry: '다시 시도',
  cancel: '취소',
  confirm: '확인',
  close: '닫기',
  unknownError: '알 수 없는 오류가 발생했습니다.',
  networkError: '네트워크에 연결할 수 없습니다.',
} as const;

/** The full copy table. Korean is the source of truth; English mirrors it. */
export type Strings = {[K in keyof typeof ko]: string};

export const en: Strings = {
  appName: 'PADIEM',
  chatTab: 'Chat',
  clawTab: 'Claw',
  historyTab: 'History',
  settingsTab: 'Settings',

  signInTitle: 'Sign in to PADIEM',
  signInSubtitle: 'Sign in with Google to start working with your AI assistant.',
  signInWithGoogle: 'Sign in with Google',
  signInWithPassword: 'Sign in with email or username',
  identifierLabel: 'Email or username',
  passwordLabel: 'Password',
  signIn: 'Sign in',
  signOut: 'Sign out',
  signingIn: 'Signing in…',

  handoffTitle: 'Sign in from your browser',
  handoffInstructions:
    'Sign in with Google in the browser, then enter the code shown below.',
  handoffCodeLabel: '8-character sign-in code',
  handoffStatus: 'Waiting for sign-in…',
  handoffPending: 'Finish the sign-in in your browser.',
  handoffReady: 'Confirmed. Returning to the app…',
  handoffConfirm: 'Confirm code',
  handoffExpired: 'The sign-in window expired. Please try again.',

  newConversation: 'New conversation',
  recentConversations: 'Recent conversations',
  searchConversations: 'Search conversations',
  noConversations: 'No saved conversations yet.',
  deleteConversation: 'Delete conversation',
  deleteConversationConfirm: 'Delete this conversation?',

  messageInputPlaceholder: 'Type a message',
  send: 'Send',
  stop: 'Stop',
  attach: 'Attach a file',
  mic: 'Voice input',
  voiceMode: 'Voice conversation',

  modelLabel: 'AI tier',
  modelUnavailable: 'Not available',
  modelSaveFailed: 'Could not save the tier.',

  voiceM1: 'Dictate, then send manually',
  voiceM2: 'Text answer after speaking',
  voiceM3: 'Text and voice answer',
  voiceM4: 'Voice call screen',
  voiceListening: 'Listening…',
  voiceThinking: 'Thinking…',
  voiceSpeaking: 'Speaking…',
  voiceUnavailable: 'Voice is not available right now.',
  voiceSpeak: 'Read aloud',

  clawConnected: 'PC connected',
  clawDisconnected: 'PC not connected',
  clawConnect: 'Connect PC',
  clawRefresh: 'Refresh connection',
  clawRun: 'Run task',
  clawRunning: 'Running task…',
  clawApprove: 'Approve',
  clawReject: 'Reject',
  clawRuns: 'Recent tasks',
  clawNoRuns: 'No tasks have run yet.',
  clawDevice: 'Connected PC',
  clawNoDevice: 'No connected PC.',

  settingsTitle: 'Settings',
  apiBaseUrl: 'Server address',
  language: 'Language',
  member: 'Member grade',
  account: 'Account',
  signedInAs: 'Signed in as',
  guest: 'Sign-in required',

  errorTitle: 'Error',
  retry: 'Try again',
  cancel: 'Cancel',
  confirm: 'Confirm',
  close: 'Close',
  unknownError: 'Something went wrong.',
  networkError: 'Could not reach the network.',
};

export type Locale = 'ko' | 'en';

const TABLES: Record<Locale, Strings> = {ko, en};

export function stringsFor(locale: Locale): Strings {
  return TABLES[locale];
}
