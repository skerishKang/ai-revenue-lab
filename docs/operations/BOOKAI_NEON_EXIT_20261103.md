# 북AI 원격 저장소 종료 조사와 이전 계획

작성일: 2026-11-03

조사 기준: 수정 전 브랜치 HEAD `1d208c2`의 코드 경로와 현재 앱 매핑 코드. 운영 DB·로그·계정에 접속하지 않았다.

## 운영 활성 판정

코드에는 로그인 세션 설정 뒤 원격 어댑터를 활성화하고 상태를 확인하는 경로가 있었다. 앱 코드만으로는 운영 Worker 설정, 실제 호출 성공 여부, 데이터 보유 여부를 확인할 수 없어 운영에서 실제 켜져 있었는지는 **확인 불가**다. 아래 표의 “코드상 경로”는 동작하도록 작성된 코드가 있다는 뜻이며 실제 운영 사용량을 뜻하지 않는다.

## 1. 사전 조사표

| 기능 | 코드가 읽거나 쓰던 정보 | 코드상 활성 경로와 근거 | 운영에서 켜져 있었는지 |
|---|---|---|---|
| 독서 본문·서지 원격 어댑터 | `sources`, `works`, `content_versions`, `content_unit_index`, `source_passages`, `passage_translations` | 목록·본문 조회: `apps/bookai/public/index.html@1d208c2:2468-2542`; 로그인 설정에서 enable 호출: 같은 파일 `:2941-2952` | **확인 불가**. 로그인 후 호출 경로는 있었음 |
| 인물·관계·정답 카드 | `entities`, `entity_aliases`, `entity_mentions`, `entity_relationships`, `answer_cards`, `answer_card_sources` 조회 | 조회 함수: `index.html@1d208c2:2561-2581`; Hybrid AI 원격 스냅샷: `storymemory-legacy-hybrid-ai-v1.js@1d208c2:57-90` | **확인 불가**. 원격 어댑터를 설치할 수 있는 경로였음 |
| 개인 기록·읽기 위치 | `memories`, `annotations`, `reader_progress`, `recall_items`; 기억·주석은 조회/추가/갱신/삭제, 위치와 복습 항목은 조회 | 원격 호출: `index.html@1d208c2:2584-2712`; 로그인 뒤 동기화: 같은 파일 `:3308-3336` | **확인 불가**. 인증 후 동기화 호출 경로는 있었음 |
| 자동 팩 레지스트리 | `pack_registry`, `pack_versions` 초안 등록 | writer 및 POST: `storymemory-auto-pack-runtime.js@1d208c2:117-130`; UI 연결은 `storymemory-auto-pack-ui.js@1d208c2:1-35` | **확인 불가**. 사용자 동작 시 등록 경로가 있었음 |
| 팩 마켓·설치 | 공개 팩·버전·검증서 조회, `pack_installs` 조회/추가/삭제 | provider: `storymemory-pack-marketplace-runtime.js@1d208c2:82-98` | **확인 불가** |
| 팩 권한·구매 | `pack_offers`, `pack_entitlements`, `pack_purchase_transactions` 조회 | provider: `storymemory-pack-entitlement-runtime.js@1d208c2:53-59` | **확인 불가** |
| 팩 평점·의견·제안 | `pack_ratings`, `pack_rating_summary`, `pack_feedback`, `pack_version_proposals`; 평가·의견·초안·검토 상태 | provider: `storymemory-pack-lifecycle-runtime.js@1d208c2:29-41` | **확인 불가** |
| 팩 검증 | 공개 검증 상태와 `pack_verification_requests` 조회/요청 생성 | provider: `storymemory-pack-verification-runtime.js@1d208c2:50-63` | **확인 불가** |

표에 적은 테이블은 코드에 명시된 접근 대상이다. 운영 데이터베이스에 실제 테이블이나 행이 있었는지는 이번 읽기 전용 코드 조사로 확인하지 않았다.

## 2. 기능별 처리

| 기능 | 선택 | 처리 |
|---|---|---|
| 독서 기록·메모·밑줄·이어 읽기 | **(a) 기기 저장 + 계정 기록** | 브라우저의 기존 기기 저장을 유지한다. 로그인 사용자의 기존 `BookAISync`가 `/api/bookai/records`로 동기화한다. `bookai-records.js:4-35`는 메모/저장 대화를 `note`/`ai_chat`, 주석을 `highlight` 또는 `note`, 읽기 위치를 `progress`로 바꾼다. |
| 저장된 AI 대화 | **(a) 기기 저장 + 계정 기록** | 사용자 기억 저장 형식의 AI 항목을 `ai_chat` 기록으로 변환한다. 일반 AI 요청 경로는 변경하지 않았다. |
| 기존 본문·원격 메타데이터 조회, `ping` | **(b) 중단** | 두 독서 화면의 어댑터를 항상 비활성화했다. 요청 함수는 네트워크 호출 전에 거부하고, 상태·ping은 로컬 결과를 돌려준다. 로그인 경로의 `enableRemote`는 예외 없이 성공 형태의 비활성 결과를 반환한다. |
| 자동 팩 생성·레지스트리 등록 | **(b) 화면 숨김, 원격 등록 제거** | 레지스트리 writer를 제거하고 런처·패널을 숨겼다. 이미 기기에 저장된 산출물은 읽거나 지우지 않는다. 자동 공개는 수행하지 않는다. |
| 팩 마켓·설치·이용 권한·구매 | **(b) 화면 숨김, provider 제거** | 원격 provider와 UI 자동 연결을 제거했다. 두 독서 화면에서 관련 진입점과 패널을 감춘다. |
| 팩 평점·피드백·버전 제안·검증 | **(b) 화면 숨김, provider 제거** | 원격 저장/조회 provider와 자동 연결을 제거했다. |
| Hybrid AI 원격 정답 카드·관계·Memory | **(b) 원격 조회 중단** | 원격 스냅샷은 빈 결과를 반환한다. 정적 본문 검색 경로는 유지한다. 사용자가 저장한 AI 대화 기록은 위의 `ai_chat` 동기화 경로를 유지한다. |

주요 구현 위치는 `apps/bookai/public/index.html`, `apps/bookai/public/readback_index.html/index.html`, `apps/bookai/public/storymemory-*-runtime.js`, 관련 팩 UI 파일이다. 두 독서 화면의 팩 패널은 모두 숨겼다. `apps/storymemory`는 수정하지 않았다.

## 3. 남아 있을 수 있는 데이터와 이전 초안

현재 원격 DB를 열지 않았으므로 아래는 **남아 있다고 확인된 데이터가 아니라, 이전 코드가 접근하도록 되어 있던 데이터 종류**다.

| 데이터 종류 | 이전 계획 |
|---|---|
| 개인 메모·기억·저장한 AI 대화 | 소유자를 확인한 항목만 기기 저장 형식으로 변환한다. 기존 mapper 기준 `note`와 `ai_chat`로 저장한 뒤 계정 로그인 상태에서 `BookAISync` → `/api/bookai/records` 경로를 사용한다. |
| 밑줄·주석 | 기존 annotation 의미를 보존해 `highlight` 또는 `note` 기록으로 변환한다. |
| 이어 읽기 위치·진도 | `progress` 기록으로 변환한다. 각 계정의 소유자와 출처 키를 확인하고, 중복 가져오기는 안정적인 원본 식별자로 막는다. |
| 복습 카드·Recall 상태 | 기존 COM2 기록 mapper에는 전용 Recall 형식이 없다. 의미·소유자 매핑이 정해질 때까지 자동 이전 대상에서 제외한다. |
| 책·출처·본문·번역·인물 관계·정답 카드 | 사용자 기록이 아니며 COM2 기록 형식과 대응하지 않는다. 앱의 정적 콘텐츠 제공을 유지하고 개인 기록 API로 복사하지 않는다. |
| 팩 카탈로그·버전·설치·권한·구매·평점·피드백·제안·검증 상태 | `/api/bookai/records`의 지원 종류와 맞지 않는다. 이번 이전에 섞지 않는다. 보존/정리 필요성과 담당 제품을 별도로 정한 뒤 처리한다. |
| 기기에 이미 저장된 비공개 팩 산출물 | 이 변경은 기존 값을 삭제하지 않는다. COM2로 자동 복사하지도 않는다. |

실제 이전은 하지 않았다. 초안 절차는 ① 원격 DB 접근 권한이 있는 담당자가 읽기 전용 백업을 만든다 ② 사용자 소유를 증명할 수 있는 기록만 기존 mapper의 `note`/`ai_chat`/`highlight`/`progress` 형태로 변환한다 ③ 대상 계정에서 중복·건수·내용을 검증한다 ④ 승인된 계정 기록 API 동기화로 반영한다. 소유자를 추정하지 않고, 원본을 삭제하거나 원격 프로젝트를 정리하는 작업은 이 절차에 포함하지 않는다.

Neon에 남은 데이터의 실제 종류와 건수, 운영 사용 여부는 접속 자격과 별도 승인 절차가 필요한 컴1 레인에서 확인한다. 이번 작업은 원격 접속·이전·삭제·프로젝트 정리를 수행하지 않았다.

## 4. 개인정보처리방침 메모

main에 올라온 `#6728` 초안 `docs/legal/drafts/services/bookai_ko.md:31`에 원격 저장소 국외 이전 문장이 남아 있다. 법무/CTO가 해당 초안을 갱신할 때 북AI 원격 저장소 종료 방침에 맞춰 이 문장을 제거하거나 실제 이전 구조로 다시 쓴다. 이 브랜치에서는 법률 초안을 수정하지 않았다.

## 5. 확인 결과와 한계

- 신규 `apps/bookai/tests/bookai-neon-exit.test.mjs`: 3/3 통과. 런타임 코드에서 원격 호스트/adapter 표식 부재, 두 독서 화면의 네트워크 전 차단, 팩 UI 숨김 및 계정 기록 경로를 확인한다.
- 북AI Node 단위 시험: 18/18 통과. `apps/bookai/test_thought_filter.cjs`: 5가지 응답 사례 통과.
- 북AI reachability 및 Chat `test_bookai_records_*.py`: 37/37 통과.
- Node Playwright를 요구하는 브라우저 스크립트는 이 PC에 `playwright` 모듈이 없어 시작되지 않았다. Python Playwright 기반 도달성 시험은 실행되어 통과했다.
- 비밀 값은 출력하거나 문서화하지 않았다. 운영 요청·운영 DB 접근·실제 데이터 이전·배포는 하지 않았다.
