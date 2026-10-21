import type { ConnectorCard, Conversation, ModelChoice } from "./types";

/**
 * #5298 — fixture data for the clone's first screen.
 *
 * The operational product answers through the signed-in B62/B14 API. This
 * clone runs without an account and without a backend, so it renders from
 * local fixtures. Every fixture reply is marked `fixture: true` and the UI
 * says so, so a fixture answer can never be read as a live product answer.
 */

export const FIXTURE_NOTICE =
  "복제본 미리보기입니다. 답변은 로컬 fixture에서 생성되며 실제 모델 호출은 하지 않습니다.";

/** A prompt fragment that makes the fixture answer fail, so the error and retry states are reachable. */
export const FIXTURE_FAILURE_TRIGGER = "[오류]";

export const MODEL_CHOICES: ModelChoice[] = [
  {
    id: "tier-default",
    label: "Padiem Plus",
    description: "기본 등급에서 사용 가능한 표준 실행 모델",
  },
  {
    id: "tier-fast",
    label: "빠른 응답 모델",
    description: "짧은 응답에 유리한 경량 실행 모델",
  },
  {
    id: "tier-deep",
    label: "고성능 모델",
    description: "긴 문맥과 복잡한 요청에 적합한 실행 모델",
  },
  {
    id: "tier-extended",
    label: "확장 컨텍스트 모델",
    description: "긴 문서와 다중 파일 요청을 위한 확장 실행 모델",
  },
];

export const CONNECTOR_CARDS: ConnectorCard[] = [
  {
    id: "pc",
    label: "컴퓨터 연결하기",
    description: "내 컴퓨터에서 직접 작업하기",
    state: "unknown",
  },
  {
    id: "drive",
    label: "구글 드라이브",
    description: "클라우드 파일로 작업하기",
    state: "unknown",
  },
  {
    id: "github",
    label: "GitHub",
    description: "코드·프로젝트 작업하기",
    state: "unknown",
  },
];

const FIXTURE_CONVERSATIONS: Conversation[] = [
  {
    id: "chat_fixture_1",
    title: "주간 일정 정리",
    product: "chat",
    updatedAt: "2026-10-20T09:12:00+09:00",
    messages: [],
  },
  {
    id: "chat_fixture_2",
    title: "견적서 초안 검토",
    product: "chat",
    updatedAt: "2026-10-19T18:40:00+09:00",
    messages: [],
  },
  {
    id: "chat_fixture_3",
    title: "회의록 요약 요청",
    product: "chat",
    updatedAt: "2026-10-18T11:05:00+09:00",
    messages: [],
  },
  {
    id: "claw_fixture_1",
    title: "드라이브 파일 정리",
    product: "claw",
    updatedAt: "2026-10-17T16:22:00+09:00",
    messages: [],
  },
];

export function createFixtureConversations(): Conversation[] {
  return FIXTURE_CONVERSATIONS.map((conversation) => ({
    ...conversation,
    messages: conversation.messages.map((message) => ({ ...message })),
  }));
}

export interface FixtureReply {
  title: string;
  body: string;
}

const FIXTURE_REPLIES: FixtureReply[] = [
  {
    title: "정리된 초안",
    body: "요청하신 내용을 정리했습니다.\n\n1. 먼저 확인이 필요한 항목을 먼저 정리했습니다.\n2. 다음 실행 순서를 제안했습니다.\n3. 실행에 필요한 승인과 권한을 따로 표시했습니다.\n\n이 복제본은 실제 백엔드에 연결되어 있지 않아, 이 내용은 로컬 fixture로 생성되었습니다.",
  },
  {
    title: "실행 계획",
    body: "요청을 실행 가능한 단계로 나누었습니다.\n\n- 준비: 연결 상태와 권한을 확인합니다.\n- 실행: 승인된 범위 안에서만 작업을 진행합니다.\n- 결과: 실행 결과와 근거를 원대화에 표시합니다.\n\n실제 도구 실행은 아직 백엔드에 연결되어 있지 않습니다.",
  },
];

export function pickFixtureReply(prompt: string): FixtureReply {
  const index = Math.abs(prompt.trim().length) % FIXTURE_REPLIES.length;
  return FIXTURE_REPLIES[index];
}
