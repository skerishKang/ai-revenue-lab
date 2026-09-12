# PADIEM Chat / Claw Copy & Glossary V1

Status: CENTRAL copy authority
Locales: Korean (ko), English (en)

## Principles

1. Product names stay as product names: Padiem, Padiem Chat, Padiem Claw.
2. Korean copy should sound like a Korean product, not a literal translation.
3. English copy should be concise and operational, not marketing-heavy inside the app.
4. The same concept must use the same term across Chat and Claw.
5. Error states must be truthful and actionable.
6. Preview and real execution must never be linguistically conflated.

## Canonical terms

| Concept | Korean | English | Notes |
|---|---|---|---|
| Workspace | 작업공간 | Workspace | UI noun |
| Project | 프로젝트 | Project | Keep familiar loanword |
| New chat | 새 채팅 | New chat | |
| Settings | 설정 | Settings | |
| Appearance | 화면 | Appearance | Korean consumer-facing section may use 화면 |
| Theme | 테마 | Theme | |
| Language | 언어 | Language | |
| File | 파일 | File | |
| Project files | 프로젝트 파일 | Project files | |
| Saved answer | 저장한 답변 | Saved answer | |
| Connector | 연결 서비스 | Connector | 커넥터 allowed in technical surfaces |
| Skill | 스킬 | Skill | |
| Task | 작업 | Task | |
| Alert | 알림 | Alert | |
| Preview | 미리보기 | Preview | Never imply completed backend execution |
| Real run | 실제 실행 | Real run | |
| Run | 실행 | Run | |
| Retry | 다시 시도 | Retry | |
| Result | 결과 | Result | |
| Source | 출처 | Source | |
| Counterparty | 거래처 | Counterparty | Business workflow |
| Quote | 견적서 | Quote | |
| Purchase order | 발주서 | Purchase order | Avoid ambiguous Order in user-facing business-document copy |
| Reply draft | 답장 초안 | Reply draft | |
| Request summary | 요청사항 정리 | Request summary | |
| Open document | 문서 열기 | Open document | |
| Download | 다운로드 | Download | |
| Save | 저장 | Save | |
| Approval | 승인 | Approval | |
| Evidence | 근거 | Evidence | 증거 only where legal/audit meaning is intended |
| Connection error | 연결 오류 | Connection error | |
| Timeout | 응답 시간 초과 | Response timed out | |
| Sign in | 로그인 | Sign in | |
| Sign out | 로그아웃 | Sign out | |

## Claw canonical positioning

### Korean

Padiem Claw

받은 업무 요청을 붙여넣으면 내용을 정리하고, 견적서·발주서·답장 같은 업무 초안을 준비해 주는 AI 작업공간입니다.

### English

Padiem Claw

An AI workspace that turns incoming business requests into structured summaries and work-ready drafts such as quotes, purchase orders, and replies.

## Preview vs execution

### Korean

- 미리보기: 저장하거나 실행하지 않고 결과 형태를 먼저 확인합니다.
- 실제 실행: AI가 서버에서 작업을 처리하고, 지원되는 경우 문서를 준비합니다.

### English

- Preview: Check the expected result without saving or executing the real workflow.
- Real run: Let AI process the task on the server and prepare a document when supported.

## Canonical errors

| Purpose | Korean | English |
|---|---|---|
| generic | 작업을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요. | We couldn’t complete the task. Please try again shortly. |
| invalid input | 입력 내용을 확인한 뒤 다시 시도해 주세요. | Check the input and try again. |
| empty request | 먼저 요청 내용을 입력해 주세요. | Enter the request before continuing. |
| rate limited | 요청이 많아 잠시 처리할 수 없습니다. 잠시 후 다시 시도해 주세요. | We’re handling a high number of requests. Please try again shortly. |
| sign-in required | 계속하려면 다시 로그인해 주세요. | Sign in again to continue. |
| storage | 문서를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요. | We couldn’t save the document. Please try again shortly. |
| connection | 서버에 연결하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요. | We couldn’t connect to the server. Check your connection and try again. |

## Prohibited copy patterns

Do not use:

- success wording after backend/network failure;
- AI result labels for client-side echoed user text;
- untranslated English UI inside the Korean locale when a canonical Korean term exists;
- developer-oriented phrases such as backend route unavailable in normal user-facing screens;
- inconsistent synonyms for the same action across Chat and Claw.

## Key parity rule

Every user-facing locale key must exist in both ko and en.

If one locale needs a structurally different sentence for naturalness, meaning parity matters more than word-for-word parity.