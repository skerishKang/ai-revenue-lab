# 임의 상한 2차 감사 — #6460 4번 · #5882 A 목록 (2026-11-02)

- 문서 전용 조사. **코드 변경 없음.** 기준판: `origin/main` `911464877` (2026-11-02).
- 대표 방침: **임의 상한 금지 — 시간 상한으로 실패시키지 않고 진행 중 + 경과 시간을 표시한다**(docs/architecture/PC_LANE_NO_DEADLINE_DESIGN_20261026.md).
- 1차 정리: 코드에 박힌 PADIEM 자체 제한은 #5872/#5875/#5877/#5862/#5876에서 걷어졌고, 컴2 이전(10-31, #5784/#5881)으로 Cloudflare 고정 한도가 사라진 곳이 많다(docs/architecture/FILE_LANE_COM2_MIGRATION_20261026.md). 오늘 기준 새로 바뀐 것: 업로드 tus 조각화(90MB·1GiB, 브랜치 `feat/chunked-upload-projects-261101` `a586666af` — **main 병합 전**, 추적 #6579~#6584), 앞단 API 읽기 30초·로그인 콜백 30초·업로드 120초·기타 8초.
- 방법: 저장소 전체에서 상수·본문 한도·타임아웃을 조사하고, "사용자가 하던 작업을 실패시키는가"를 기준으로 걸러냈다. 폼 입력 길이·ID 길이 같은 유효성 상수는 작업을 막지 않아 부록으로만 기록했다.

## 0. 요약

| 판정 | 개수 |
|---|---|
| 제거 제안 | 2 |
| 상향 제안 | 6 |
| 유지(근거 명시) | 31 |
| 외부(바꿀 수 없음) | 7 |

## 1. 판정 기준

- **제거**: 그 한도가 없어도 안전하고(다른 방어가 있고), 지금 사용자 작업을 실패시킨다.
- **상향**: 실한도는 다른 곳(디스크·DB·공급자)에 있고, 현재 값이 그보다 작아 불필요하게 막는다.
- **유지**: 보안·프로토콜·자원 보호·실측 근거가 있거나, 이미 외부 실한도와 일치한다.
- **외부**: 우리 코드가 못 바꾸는 물리·계약 한도.

## 2. 꼭 볼 것 12항목 — 체크 결과

| # | 항목 | 확인 결과 |
|---|---|---|
| 1 | PC 읽기 20MB | **4곳이 같은 20MB를 반복**(실행기·Engine·Chat 라우트·history) — Cloudflare Worker 버퍼 시절 잔재. #6460 배선(출력 저장 핸들 + 페이징 read_output)으로 우회로는 이미 깔려 있음 → 상향→제거 경로. §3-1 |
| 2 | 실행기·Chat 6MB 동시 | 실행기 `MAX_READ_BYTES=6MB` · Chat `_MAX_BODY_BYTES=6MB` · 로컬 전송 모델 경로 6MB가 서로를 참조하는 봉투. 큰 결과는 이미 무제한 결과 프레임(`_MAX_RESULT_BODY_BYTES=None`)과 출력 핸들로 우회 → 유지하되 큐 파트 상향과 묶어 재검토. §3-2 |
| 3 | 저장 개수 상한 | **개수 상한 없음**(목록 페이지 100만 있음). 행 2MiB는 D1 외부 한도와 일치. 다만 저장 본문 입력 96KB가 행 한도 2MB보다 작아 불일치 → 상향. §3-3 |
| 4 | 명령 타임아웃 | ToolSpec 고정 300초는 **이미 제거**(#4379 — `tool_runtime.py:609` "PADIEM deadline 없음, None은 끝까지 대기"), `MAX_COMMAND_BYTES=None`도 제거됨. 남은 것은 디스패치 TTL 600초(설계 문서가 lease 분리 후속으로 명시) → 유지. §3-2 |
| 5 | SNS 10MiB·8장 (#5872) | 1MB→10MiB 상향 반영됐고 **오늘 실측 완료**, 합계 상한 없음(정책 §785). 엔진 Slack/Telegram 포트의 10MB는 **응답 읽기** 상한으로 별개 — 유지. 사진 8장은 코드에서 상수 미확인(브라우저 리사이즈 1920px만 확인) — 이슈 #5872 기준 유지. §3-5 |
| 6 | B66 10MiB (#5877) | 미리보기·키라/체험 파일럿 응답 10MB, PDF 응답 32MB, 번들 32/48/20/10MB — #5877 상향분 **오늘 실측 완료**(정책 §784) → 유지. §3-4 |
| 7 | 웹 XLSX 인라인 10MB | `WEB_XLSX_INLINE_MAX_BYTES=10_000_000` — 총량은 이미 1GiB. 10MB는 Worker 메모리 시절 잔재 추정 → 컴2 파싱 경로에서 상향 실측 권장. §3-3 |
| 8 | 앞단 8초·30초·120초 | 8초(일반)/30초(API 읽기·로그인 콜백)/65초(apps AI) + tus 120초(브랜치). 역할이 분리돼 있고 실패 시 재시도·이어올리기가 있음 → 유지. §3-6 |
| 9 | tus 90MB·1GiB | **유지** — 90MB는 Cloudflare 무료 100MB/요청 아래 여유 + 재개 단위 최소화, 1GiB는 D1 행 2MiB·R2 원본·컴2 디스크로 정의된 총량. §3-1 |
| 10 | 첨부 개수 10개 | 코드는 **한 번에 1개**(`attachments.py:174` "현재는 파일을 한 번에 하나만") — 지시서의 "10개"와 불일치. 서버는 개당 1GiB까지 받으므로 다중화 여지 큼 → 상향(다중 첨부). §3-1 |
| 11 | 대화·메시지 길이 상한 | 임의 길이 상한 없음(브라우저 본문 무제한 — #4379/#5882 계열 정리 완료). 저장 미리보기 8,000자는 "잘림 표시"가 명시돼 유지, 조립 봉투 5.5MB는 전송 6MB 아래 여유로 유지. §3-1 |
| 12 | 모델 입력 토큰 한도 | 고정 토큰 상한 없음 — 카탈로그 `context_window` × 비율(기본 0.60, 허용 0.2~0.9, 최소 2,048)로 압축 시작, 초과분은 아카이브+회수(#6460) — 임의 상한이 아니라 모델 보호 장치 → 유지. §3-7 |

## 3. 전체 상한 표

### 3-1. Chat (COM2) — 업로드·대화·PC 결과

| 이름 | 값 | 위치 | 생긴 이유 | 제안 | 근거 |
|---|---|---|---|---|---|
| tus 조각 상한 | 90MiB | `apps/padiem-chat/app/tus_project_upload.py` (브랜치 `a586666af`, main 병합 전) | 외부 우회 설계 | **유지** | Cloudflare 무료 100MB/요청 아래 여유 + 끊김 재개 단위 최소화(#6579~#6584) |
| tus 총량 | 1GiB | 같음 | 외부 정합 | **유지** | D1 행 2MiB(추출 텍스트)·R2 원본·컴2 디스크로 정의되는 총량 |
| tus 미완성 청소 | 24시간 | 같음 (`PADIEM_TUS_CLEANUP_SECONDS`) | 자원 보호 | **유지** | 디스크 고갈 방지, 재개 윈도로 충분 |
| 채팅 첨부 개수 | **1개** | `apps/padiem-chat/app/attachments.py:174` | 이유 불명(단계 제한 추정) | **상향**(다중 첨부) | 서버는 개당 1GiB 수용(`MAX_IMAGE_BYTES=1GiB`, `attachments.py:18`) — 사용자 체감 최대 상한 |
| 첨부 크기 | 1GiB | `attachments.py:18`, `packages/padiem-ai-core/padiem_ai_core/b14_multimodal.py:13` | 1차 정리(#5872~)로 1GiB화 | **유지** | 이미 외부 실한도(디스크·전송)에 맞춰짐 |
| 저장된 대화 메시지 미리보기 | 8,000자 | `apps/padiem-chat/app/history.py:14` | 화면·행 크기 보호 | **유지** | 잘림을 명시 표기(`history.py:564`) — 전문은 공급자 기록으로 존재, 사용자 작업을 실패시키지 않음 |
| 대화 조립 봉투 | 5.5MB | `history.py:15` (`MAX_MODEL_CONTEXT_BYTES`) | Cloudflare 시절 6MB 전송 봉투 아래 여유 | **유지** | 전송 봉투(6MB)와의 정합 유지 — 봉투를 올릴 때 함께 재검토 |
| 대화 제목 | 80자 | `history.py:16` | 화면 표시 | **유지** | 표시 상수 |
| PC 읽기 원본 총량 | 20MB | `history.py:80` (`ORACLE_MESH_PC_READ_ORIGINAL_MAX_BYTES`) | Cloudflare Worker 버퍼 잔재 | **상향→제거** | #6460 출력 핸들+페이징으로 원본 통째 전송이 이미 불필요 — 실행기·Engine과 함께 변경(§3-2) |
| 메시 본문(일반) | 6MB | `oracle_mesh_read_return_routes.py:164` | 전송 봉투(하위호환) | **유지** | 큰 결과는 무제한 결과 프레임(`:163` `None`)·출력 핸들로 우회됨 |
| 메시 결과 프레임 | 무제한 | `oracle_mesh_read_return_routes.py:163` | 1차 정리 | **유지** | 이미 제거 상태 — 회귀 금지 |
| 메시 presence 본문 | 8KiB | `oracle_mesh_read_return_routes.py:194` | 하트비트 최소 프레임 | **유지** | 프로토콜 프레임 |
| 디스패치 TTL | 600초 | `oracle_mesh_read_return_routes.py:154` | Cloudflare 시절 잔재 | **유지(설계 대기)** | no-deadline 설계가 "집기 lease와 실행 마감 분리"를 후속 구현으로 명시 — 함부로 올리면 멱등성 해침 |
| PC 파일 읽기 상한 | 20MB | `oracle_mesh_read_return_routes.py:3450` | Cloudflare 잔재 | **상향→제거** | §3-2와 동일 변경 묶음 |
| 저장 본문 입력 | 96KB | `saved_output_routes.py:19` | 이유 불명(행 한도 2MB보다 작음) | **상향(2MB 정렬)** | 행 한도는 2MiB(`saved_outputs.py:14`) — 입력 96KB가 유일한 병목 |
| 저장 행 크기 | 2MiB | `saved_outputs.py:14` | D1 행 한도 정합 | **유지** | 외부(D1)와 일치 |
| 저장 목록 페이지 | 100 | `saved_outputs.py:10` | 페이지네이션 | **유지** | 개수 상한 아님(무한 페이지) |
| 웹 XLSX 총량 | 1GiB | `workspace_storage.py:18` | 컴2 디스크 기준 | **유지** | FILE_LANE 문서: 상수 1GiB는 컴2 경로에서 실의 있음 |
| **웹 XLSX 인라인** | **10MB** | `workspace_storage.py:22` | Worker 메모리 시절 잔재 추정 | **상향(실측 후)** | 컴2 CPython 파싱 경로 — 100MB급 견적 XLSX 인라인 처리 가능 여부 실측 |
| 앱 AI 타임아웃 | 55초 | `apps_ai.py:31` | 앞단 65초와 정합 | **유지** | 앞단(65초)이 먼저 끊기지 않도록 하위 정렬 — 이미 정합 |
| BYOK 응답 읽기 | 10MB | `byok_client.py:39` | 응답 버퍼 보호 | **유지** | 공급자 응답은 스트림 소비 — 무한 버퍼는 OOM 위험 |
| 회의록 Drive 업로드 txt | 10MB | `meeting_drive_upload_routes.py:30` | 경로별 상한 | **유지** | 회의 원문은 파일 레인(tus) 경로 사용이 원칙 — 인라인 보조 경로 |
| Drive 케이스 PDF | 16MiB | `drive_case_folder_engine.py:72` | 파서 입력 보호 | **유지** | 대형 PDF는 파일 레인 경로 |
| 오피스 선택기 파일 | 10MB | `claw_office_chooser_routes.py:63` | 경로별 상한 | **유지** | 대형 문서는 파일 레인 경로 |

### 3-2. PC·메시 레인 (실행기 + 큐 + Chat + Engine — 4곳 연쇄)

| 이름 | 값 | 위치 | 생긴 이유 | 제안 | 근거 |
|---|---|---|---|---|---|
| 실행기 읽기 봉투 | **20MB** | `apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py:147` | Cloudflare Worker 버퍼 잔재(주석에 "older servers" 하위호환 명시) | **상향→제거** | 컴2 로컬 CPython 실행기 — 결과는 큐 출력 저장(파트 업로드)으로 감. 4곳(실행기·Engine·Chat·history)이 같은 20MB를 반복 — 한 번에 변경 |
| 실행기 조각 읽기 | 6MB | `local_agent_oracle_mesh_executor.py:148` | 전송 봉투 | **유지(재검토)** | 큐 파트 상향 시 함께 |
| 실행기 명령 본문 | 무제한 | `local_agent_oracle_mesh_executor.py:146` (`MAX_COMMAND_BYTES=None`) | 1차 정리 | **유지** | 이미 제거 — 회귀 금지 |
| 실행기 presence 캐시 | 8대 | `local_agent_oracle_mesh_executor.py:124` | 메모리 | **유지** | 기기 수 증가 시 상향 검토(우선순위 낮음) |
| 실행기 결과 거부 한도 | 3회 | `local_agent_oracle_mesh_executor.py:167` | 남용 방지 | **유지** | 보안상 필요 |
| 실행기 폴링·백오프 | 60초/10초/60초 | `:59-60`, `:172` | 폴링 리듬 | **유지** | 폴링 간격은 실패 처리가 아님(방침과 무충돌) |
| 큐 내부 RPC 본문 | **1MB** | `apps/padiem-mesh-queue/internal_store.py:28` | 파트 업로드 전제(#6460) | **상향(예: 8MB)** | 21MB 출력 = 21파트 → 3파트. 큐는 컴2 로컬 서비스, 기존 1MB 파트도 그대로 수용(하위호환) |
| 큐 메서드 이름 | 64자 | `internal_store.py:29` | 유효성 | **유지** | 폼 상수 |
| Engine PC 읽기 상한 | **20MB** | `apps/padiem-ai-engine/app/claw_pc_query_step_driver.py:119` | Cloudflare 잔재(주석에 20MB 3곳 명시) | **상향→제거** | 모델은 `output_ref`(head·tail·size·handle) 페이징을 씀(#6460) — 원본 총량 상한은 점점 무의미 |
| Engine PC 청크 | 1MB | `claw_pc_query_step_driver.py:1184` | 프로토콜 단위 | **유지** | 청크 순서·무결성 검증 단위 |
| Engine 검색 행 | 50행 | `claw_pc_query_step_driver.py:908` | 응답 폭 | **유지** | 스니펫 페이징으로 이어짐 |
| PC 읽기 청크 요청 | 1MB | `apps/padiem-chat/app/claw_pc_read_command.py:26` | 프로토콜 단위 | **유지** | 상동 |
| PC 오피스 접두 읽기 | 16MiB | `claw_pc_read_command.py:35`, `claw_pc_search_command.py:34` | 형식 판별 접두 | **유지** | 매직바이트 판별용 접두 — 상한이 아니라 접두 |
| PC 검색 스캔 | 2,000파일 | `claw_pc_search_command.py:29` | 스캔 폭 | **유지** | "전체 개수 미확인" 표기와 페이지 이어가기가 설계에 있음 |
| Tool 실행 마감 | 없음(선택적) | `packages/padiem-ai-core/padiem_ai_core/tool_runtime.py:609-618` | #4379로 고정 300초 제거 | **유지** | "PADIEM deadline 없음, None은 끝까지 대기" — 방침 이행 상태 |

### 3-3. 전송·파서 (Chat↔Engine)

| 이름 | 값 | 위치 | 생긴 이유 | 제안 | 근거 |
|---|---|---|---|---|---|
| Engine 일반 요청 | 256KiB | `apps/padiem-chat/app/local_engine_transport.py:47`, `worker_orchestration.py:53` | 소형 계약 봉투 | **유지** | 모델 경로와 분리된 비모델 계약용 |
| **Engine 모델 경로 요청** | **6MB** | `local_engine_transport.py:48` | Cloudflare 시절 모델 본문 한도 잔재 | **유지(재검토)** | 문서 근거: "5.5MB UTF-8 봉투가 모델 HTTP 요청 경계 아래"(PADIEM_MODEL_CONTEXT_FIDELITY) — 컴2 직결 후 실한도는 Engine ingress — 큐 파트·5.5MB 조립과 함께 한 번에 재검토(여러 서비스) |
| Engine 응답 읽기 | 10MB | `local_engine_transport.py:49`, `worker_orchestration.py:41` | 응답 버퍼 보호 | **유지** | 스트림 경로(SSE)는 별도 — 비스트림 오류 응답만 |
| 로컬 전송 타임아웃 | 30초/600초(스트림) | `local_engine_transport.py:73,75` | 모델 유휴 예산 | **유지** | 스트림은 600초 + 진행 이벤트 — 고정 실패가 아님 |
| 스트림 오류 본문 | 64KiB | `local_engine_transport.py:77` | 오류는 한계 JSON | **유지** | 프로토콜 |
| 첨부 요청 파생 한도 | base64(1GiB)+8KiB | `local_engine_transport.py:57-58` | MAX_B14_IMAGE_BYTES 연동 | **유지** | 자동 파생 — 원 상수를 올리면 따라옴 |
| 격리 파서 입력 | (본문 봉투 공유) | `packages/padiem-ai-core/padiem_ai_core/document_parser_boundary.py` | #2824 격리 파서 — #5882 보류 목록 등재 | **유지(보류 목록)** | #5882 정본 항목 — 본 감사에서 임의 변경 금지 |

### 3-4. B66 (견적)

| 이름 | 값 | 위치 | 생긴 이유 | 제안 | 근거 |
|---|---|---|---|---|---|
| 인증 미리보기 | 10MB | `b66_certified_preview.py:17` | #5877 상향분 | **유지** | 오늘 실측 완료(정책 §784) |
| 키라·체험 파일럿 응답 | 10MB | `b66_kira_direct_pilot.py:25`, `b66_experiential_direct_pilot.py:25` | #5877 상향분 | **유지** | 상동 |
| 인증 PDF 요청/응답 | 32KB / 32MB | `b66_certified_pdf_routes.py:22-23` | 요청은 지시 JSON, 응답은 PDF | **유지** | 요청 32KB는 템플릿 지시 크기 — 실측됨 |
| 견적 번들 | 32/48/20/10MB·32멤버·압축비 1000 | `b66_certified_quote_bundle.py:26-31` | zip 폭탄 방지 + 실측 | **유지** | 압축비·멤버 상한은 보안상 필요(전개 폭발 방지) |
| B66 대화 상태 | 1MB·8턴·20항목·메모 1,000·프롬프트 4,000자 | `b66_ai_conversation.py:56-65` | 모델 입력 폭 관리 | **유지** | 실측된 대화 폭 — 임의 토큰 상한 아님 |
| 가이드 초안 | 1MB·80메시지·9,000자 | `b66_guided_draft.py:20-24` | 상동 | **유지** | 상동 |
| PC 템플릿 요청 | 4,000자 | `b66_pc_template_routes.py:46` | 모델 입력 폭 | **유지** | 상동 |

### 3-5. SNS·커넥터 (Engine 포트)

| 이름 | 값 | 위치 | 생긴 이유 | 제안 | 근거 |
|---|---|---|---|---|---|
| Slack 응답 읽기 | 10MB | `apps/padiem-ai-engine/app/slack_port_httpx.py:77` | 응답 버퍼 보호 | **유지** | #5872 실측 완료 — 발송 메시지(10MiB)와 별개 |
| Telegram 응답 읽기 | 10MB | `telegram_port_httpx.py:54` | 상동 | **유지** | 상동 |
| Slack 채널 나열 | 128 | `packages/padiem-ai-core/padiem_ai_core/slack_capability.py:72` | 조회 폭 | **유지** | 폼 상수 |
| 커넥터 PC RPC | 30/20/15/10/8초, 프레임 8KiB | `connector_native_pc_gateway_port.py:31`, `connector_pending_pc_owner_rpc.py:32`, `canonical_connector_enrollment_async_host.py:33`, `connector_owner_identity_pc_completion.py:31`, `connector_pending_pc_offer_gateway.py:25-27`, `com2_pc_offer_relay.py:16` | 연결 수립·오퍼 교환의 짧은 핸드셰이크 | **유지** | 파일 전송이 아닌 신호 교환 — 대용량은 파일 레인으로 감 |
| 로컬 연결 검사 | 10초 | `claw_local_connect_composition.py:55` | 상동 | **유지** | 상동 |
| 큐 프록시 타임아웃 | 8초 | `queue_store_proxy.py:40` | 상동 | **유지** | 상동 |

### 3-6. 앞단 (Cloudflare Worker)

| 이름 | 값 | 위치 | 생긴 이유 | 제안 | 근거 |
|---|---|---|---|---|---|
| 일반 쓰기·읽기 | 8초 | `apps/padiem-chat-front/worker.mjs:28` | 죽은 업스트림 판별 | **유지** | 장기 작업은 전용 경로로 분리 완료(tus 120초·apps AI 65초) — 8초는 연결 실패 판별용 |
| API 읽기 | 30초 | `worker.mjs:29` | 목록·조회 여유 | **유지** | 읽기는 멱등 — 실패 시 재시도 |
| 로그인 콜백 | 30초 | `worker.mjs:34` | OAuth+JWKS+identity RPC | **유지** | worker.mjs 주석의 운영 교훈 근거 |
| apps AI | 65초 | `worker.mjs:183` | 완성형 모델 응답 | **유지** | Chat 측 55초와 정합 |
| tus 조각 | 120초 | 브랜치 `a586666af`(main 병합 전) | 90MB 드레인 | **유지** | 조각 단위 — 실패해도 이어올리기 |

### 3-7. 모델·에이전트 (Engine/Core/kagent)

| 이름 | 값 | 위치 | 생긴 이유 | 제안 | 근거 |
|---|---|---|---|---|---|
| 컨텍스트 압축 시작 비율 | 0.60 (0.2~0.9) | `apps/padiem-ai-engine/app/pc_context_budget.py:16,41` | 모델 보호(카탈로그 context_window 기준) | **유지** | 고정 토큰 상한이 아니라 비율 — 임의 상한 아님 |
| 최소 압축 예산 | 2,048토큰 | `pc_context_budget.py:21` | 최소 작업 보장 | **유지** | 하한 보호 |
| 추가 시스템 컨텍스트 | 무제한 | `apps/padiem-chat/app/b14_client.py:50` (`None`) | 1차 정리 | **유지** | 이미 제거 — 회귀 금지 |
| B14 이미지 | 1GiB | `b14_multimodal.py:13` | 1차 정리 | **유지** | 실한도 정합 |
| 체크포인트 단계 | 64단계·스윕 500/2,000 | `apps/padiem-ai-engine/app/agent_durable_d1.py:25,30-31` | 하우스키핑 | **유지** | 저장소 청소 파라미터 |
| 에이전트 정의 폭 | 제목 160·설명 1,000·지침 12,000자 등 | `packages/padiem-ai-core/padiem_ai_core/agent_definition.py:27-34` | 폼 유효성 | **유지** | 입력 폼 — 작업 실패 아님 |
| 승인 창 | 24시간 | `agent_approval.py:25` | 보안상 필요 | **유지** | 승인 유효기간 |
| durable lease | 1~3,600초 | `agent_durable_lease.py:26-27` | 임대 상한 | **유지** | 잠금 설계 |
| 에이전트 이벤트 폭 | 1,000자·키 16·ID 128 | `agent_events.py:10-12` | 이벤트 폭 | **유지** | 로그 폭 |
| 계획 폭 | 32단계·입력 32,000자 | `agent_planner.py:22-25` | 계획 폭 | **유지** | 계획기 입력 폭 |
| kagent 아티팩트 | 8MB | `apps/korean-ai-code-agent/src/kagent/artifact_registration.py:50` | 스냅샷 폭 | **유지(검토)** | 대형 산출물은 PC 출력 저장 핸들 경로가 정규 경로 — 필요 시 별도 검토 |
| kagent 도움 요청 TTL | 600초 | `agent_human_control.py:12` | 승인 대기 | **유지** | 보안·운영 |
| 브라우저 임대 | 300/900초·25/100행·120초 유휴 | `browser_control_actions.py:93-95` | 최소권한 | **유지** | 보안상 필요 |
| 인증 남용 한도 | 5/50/10,000·잠금 60분 | `apps/padiem-chat/app/auth_abuse.py:13-15`, `auth_routes.py:602-606` | 보안상 필요 | **유지** | 무기한 잠금이 아니라 일일 한도+시간 잠금 |
| 관리·인증 소폼 | 256B/1KB/16KB/4KB/8KB | `account_model_selection_routes.py:35`, `platform_admin_routes.py:37`, `auth_routes.py:602`, `android_device_enrollment_routes.py:35`, `android_auth_routes.py:64,68` | 폼 유효성 | **유지** | 작업을 막지 않음 |

### 3-8. 의원3종 (council)

| 이름 | 값 | 위치 | 생긴 이유 | 제안 | 근거 |
|---|---|---|---|---|---|
| 생성 대기 | **120초** | `apps/padiem-council-apps/static/council-app.js:90` | 시간 상한으로 실패(방침 위반 소지) | **상향 또는 진행 표시 전환** | 대표 방침: 시간 상한으로 실패시키지 않음 — 진행 중 + 경과 표시로 바꾸면 120초 자체가 사라짐(단일 파일) |
| 사진 리사이즈 | 1,920px | `static/photo-resize.js:19` | 화면 품질·메모리 | **유지** | 표시용 파이프라인 |

## 4. 외부 한도 — 우리가 못 바꾸는 것 (표기 전용)

| 한도 | 값 | 영향 |
|---|---|---|
| Cloudflare 무료 요금제 본문 | 약 100MB/요청 | tus(90MB 조각) 병합 전까지 업로드 엣지 한도 — 병합 후 우회 |
| D1 행 크기 | 2MiB | 프로젝트 파일 추출 텍스트·저장 행(2MB)이 여기에 정합 |
| R2 단일 PUT / 멀티파트 | 5GiB / 10,000파트 | 1GiB 원본 저장에는 여유 |
| Slack·Telegram 공급자 | 공급자 기준 | 발송 10MiB는 #5872 실측으로 공급자 기준 확인 완료 |
| COM2 디스크 | NVMe 128GB(여유 33GB)·HDD 2TB | tus 총량 1GiB·출력 저장의 실한도 — 여유 모니터링 필요 |
| systemd ProtectSystem=strict | 기록 경로 제한 | tus 임시 디렉터리는 허용 경로만 사용(운영 문서 §8-1) |
| Cloudflare Worker 자원 | CPU/메모리 | 파일 파싱·PC 결과 버퍼링은 컴2 이전으로 이미 우회 — 잔여 경로는 원冻结 |

## 5. 바로 바꿔도 되는 것 (값·위치·예상 영향)

| 순 | 무엇을 | 값 | 위치 | 예상 영향 |
|---|---|---|---|---|
| 1 | 저장 본문 입력을 행 한도로 정렬 | 96KB → 2MiB | `saved_output_routes.py:19` | 저장 거절(413) 소멸. 행 한도(D1 2MiB)와 일치 — 서버 한 줄 변경, 위험 낮음 |
| 2 | 큐 내부 RPC 본문 상향 | 1MB → 8MB | `apps/padiem-mesh-queue/internal_store.py:28` | 21MB PC 출력 = 21파트 → 3파트. 큐가 큰 본문을 "받을 수 있게" 되는 것뿐이라 기존 1MB 파트 발신자는 그대로 동작(하위호환) |
| 3 | 웹 XLSX 인라인 상향 | 10MB → 100MB(실측 후 확정) | `workspace_storage.py:22` | 대형 견적 XLSX 인라인 처리. 컴2 CPython 파싱 — 메모리 스풀 영향만 실측 |
| 4 | 의원3종 생성 대기 | 120초 고정 실패 → 진행 중+경과 표시 | `council-app.js:90,203` | 긴 생성이 시간으로 죽지 않음 — 대표 방침 정합. 단일 파일 변경 |
| 5 | PC 읽기 20MB 4곳 상향→제거 | 20MB → 출력 핸들 우회 후 상한 폐지 | 실행기 `:147`·Engine `:119`·Chat `:3450`·`history.py:80` | 대형 PC 읽기가 20MB에서 막히지 않음 — #6460 배선(페이징 read_output·출력 저장) 활용. 4곳 동시 변경 필요 |

(참고: 채팅 첨부 다중화 — `attachments.py:174`의 1개 제한 해제 — 사용자 체감이 가장 크지만 UI 트레이+전송 계약 동시 변경이 필요해 "바로"에서 한 단계 뺐다. 아스트라 단독 레인으로 1건씩.)

## 6. 레인 배정 제안

- **아스트라(한 곳짜리)**: ① 저장 본문 96KB 정렬(Chat 단일) ② 웹 XLSX 인라인 상향 실측(Chat 단일) ③ 의원3종 생성 진행 표시(council 단일) ④ 채팅 첨부 다중화(Chat 서버+화면)
- **컴1 로컬(여러 서비스 연쇄)**: ① PC 읽기 20MB 4곳(실행기·Engine·Chat·history) — 출력 핸들 우회 완성 후 상한 제거 ② 6MB 봉투·큐 1MB 파트 재검토(실행기·큐·Chat·로컬 전송 4곳) — 큐 파트 상향부터 단계 적용
- **유지·감시 대상**: tus 90MB/1GiB(병합 후 엣지 413 소멸 확인), B66 실측값, Engine 포트 응답 10MB, 인증 남용 한도

## 7. 참조

- docs/architecture/PC_LANE_NO_DEADLINE_DESIGN_20261026.md — 고정 마감 폐지 설계(20MB 경계·200개 페이지·10,000개 탐색·ToolSpec 300초·_DISPATCH_TTL 600초 후속)
- docs/architecture/FILE_LANE_COM2_MIGRATION_20261026.md — 1차 걷어내기(#5872/#5875/#5877/#5862/#5876)와 물리 한도표
- docs/research/LARGE_UPLOAD_1GB_DESIGN_20261101.md — tus A안(90MB·1GiB 근거)
- docs/architecture/PADIEM_PC_REMOTE_LIMITS_WIRING_6460_20261101.md — #6460 §5-1 출력 저장·컨텍스트 압축 배선
- docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md §784-785 — B66·SNS 실측 상태
- docs/operations/PADIEM_MODEL_CONTEXT_FIDELITY_20261012.md — 14k/16k/32k 임의 컨텍스트 상한 제거·5.5MB 봉투 근거
- docs/operations/CPYTHON_P01_ENGINE_TRANSPORT_20261031.md — 로컬 전송 본문 한도(256KiB/6MB/10MB)
- 이슈: #6460(4번) · #5882(A 목록 정본) · #6579~#6584(tus) · #5872 · #5877 · #4379 · #5573 · #5881
