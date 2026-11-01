# 임의 상한 2차 감사 — #6460 4번 · #5882 A 목록 (2026-11-02)

- 문서 전용 조사. **코드 변경 없음.** 기준판: `origin/main` `5e741bce6` (2026-11-02) — 이전 세션 초안(`47fe68112`)을 최신 main에 rebase하고 tus 병합(#6584)을 반영해 완성.
- 대표 방침: **임의 상한 금지 — 시간 상한으로 실패시키지 않고 진행 중 + 경과 시간을 표시한다**(docs/architecture/PC_LANE_NO_DEADLINE_DESIGN_20261026.md).
- 1차 정리: 코드에 박힌 PADIEM 자체 제한은 #5872/#5875/#5877/#5862/#5876에서 걷어졌고, 컴2 이전(10-31, #5784/#5881)으로 Cloudflare 고정 한도가 사라진 곳이 많다(docs/architecture/FILE_LANE_COM2_MIGRATION_20261026.md).
- 이번 세션 기준 새로 바뀐 것: **tus 조각 업로드가 main에 병합**(#6584, `142bcc082` — 서버 `tus_core.py` 공용 코어 + 프로젝트·채팅 첨부·웹 XLSX 3레인, 앞단 tus 타임아웃 120초). 업로드 조각 90MiB·총량 1GiB·미완성 청소 24시간. **사용자별 저장 용량 상한은 없음 = 알려진 빈틈 D3**(§3-1 tus 총량 행, §4).
- 방법: 저장소 전체에서 상수·본문 한도·타임아웃을 조사하고, "사용자가 하던 작업을 실패시키는가"를 기준으로 걸러냈다. 폼 입력 길이·ID 길이 같은 유효성 상수는 작업을 막지 않아 유지로 기록했다. 모든 위치는 기준판 `5e741bce6`에서 줄번호까지 재확인했다. 확인하지 못한 것은 "확인 못 함"으로 적었다.

## 0. 바로 바꿔도 되는 것 5개 — 한 줄 변경·위험 낮음만

| 순 | 무엇을 | 바꿀 파일:줄 | 현재 값 → 새 값 | 한 줄 근거 |
|---|---|---|---|---|
| 1 | 저장 본문 입력을 행 한도로 정렬 | `apps/padiem-chat/app/saved_output_routes.py:19` | `96_000` → `2_000_000` | 저장 거절(413) 소멸. 행 한도 2MB(`saved_outputs.py:14`, D1 2MiB 정합)와 일치 — 서버 한 줄 |
| 2 | 큐 내부 RPC 본문 상향 | `apps/padiem-mesh-queue/internal_store.py:28` | `1_000_000` → `8_000_000` | 21MB PC 출력 = 21파트 → 3파트. 큐가 "받을 수 있게" 되는 것뿐 — 기존 1MB 발신자 그대로 동작(하위호환) |
| 3 | 웹 XLSX 인라인 경계 상향 | `apps/padiem-chat/app/workspace_storage.py:22` | `10_000_000` → `50_000_000` | 10MB 초과분은 이미 스트리밍 판정 경로로 폴백(`:486-516`)이라 실패 모드 없음 — 인라인 파싱 메모리만 COM2 실측 1회 권장 |
| 4 | 의원3종 생성 대기 연장(임시 완화) | `apps/padiem-council-apps/static/council-app.js:90` | `120000` → `300000` | 긴 생성이 120초에 시간으로 죽는 것을 막는 임시 방편(사용 `:203`). 근본 해결은 진행 중+경과 표시 전환(§3-8) — `util-menu.js`에 자체 타이머는 없음(주석 `:200`은 옛 설명) |
| 5 | 앞단 tus 조각 타임아웃 여유 | `apps/padiem-chat-front/worker.mjs:34` | `120000` → `180000` | 90MiB 조각을 120초에 못 올리는 회선(≈750KB/s 미만)의 재시도를 줄임 — 프록시 타임아웃 연장만이고 실패해도 tus 이어올리기로 동작 동일 |

(참고: 채팅 첨부 다중화 — `attachments.py:174-175`의 1개 제한 해제 — 사용자 체감이 가장 크지만 UI 트레이+전송 계약 동시 변경이 필요해 "바로"에서 한 단계 뺐다. PC 읽기 20MB 4곳 묶음도 한 줄이 아니므로 제외(§3-2).)

## 1. 요약

| 판정 | 행 수 |
|---|---|
| 바로 변경(빠른 개선) | 5 |
| 제거 제안(PC 읽기 20MB 4곳 = 1묶음) | 4 |
| 상향 제안(설계 묶음) | 1 |
| 유지(근거 명시) | 74 |
| 본문 표 행 합계 | 84 |
| 외부 한도(§4) | 7 + 자체 빈틈 D3 1 |

## 2. 판정 기준

- **바로 변경**: 한 줄 상수 변경으로 끝나고, 실패 모드가 없거나 기존 동작을 그대로 수용(하위호환)하며, 다른 서비스·화면의 동시 변경을 요구하지 않는 것.
- **제거**: 그 한도가 없어도 안전하고(다른 방어가 있고), 지금 사용자 작업을 실패시킨다.
- **상향**: 실한도는 다른 곳(디스크·DB·공급자)에 있고, 현재 값이 그보다 작아 불필요하게 막거나, 여러 곳을 한 번에 바꿔야 하는 묶음.
- **유지**: 보안·프로토콜·자원 보호·실측 근거가 있거나, 이미 외부 실한도와 일치.
- **외부**: 우리 코드가 못 바꾸는 물리·계약 한도.

## 3. 꼭 볼 것 12항목 — 체크 결과

| # | 항목 | 확인 결과 |
|---|---|---|
| 1 | PC 읽기 20MB | **4곳이 같은 20MB를 반복**(실행기 `local_agent_oracle_mesh_executor.py:147`·Engine `claw_pc_query_step_driver.py:119`·Chat `oracle_mesh_read_return_routes.py:3450`·history `history.py:80`) — Cloudflare Worker 버퍼 시절 잔재. #6460 배선(출력 저장 핸들 + 페이징 read_output)으로 우회로는 이미 깔려 있음 → 상향→제거 경로. §3-1/§3-2 |
| 2 | 실행기·Chat 6MB 동시 | 실행기 `MAX_READ_BYTES=6MB`(`:148`)·Chat `_MAX_BODY_BYTES=6MB`(`oracle_mesh_read_return_routes.py:164`)·로컬 전송 모델 경로 6MB(`local_engine_transport.py:48`, `worker_orchestration.py:45`)가 서로를 참조하는 봉투. 큰 결과는 이미 무제한 결과 프레임(`_MAX_RESULT_BODY_BYTES=None`, `:163`)과 출력 핸들로 우회 → 유지하되 큐 파트 상향과 묶어 재검토. §3-2/§3-3 |
| 3 | 저장 개수 상한 | **개수 상한 없음**(목록 페이지 100, `saved_outputs.py:10`). 행 2MB는 D1 외부 한도와 일치. 저장 본문 입력 96KB가 행 한도 2MB보다 작은 불일치는 빠른 개선 1번으로 해소 → §3-1 |
| 4 | 명령 타임아웃 | ToolSpec 고정 300초는 **이미 제거**(`tool_runtime.py:609-611` "#4379: a Tool call has no PADIEM deadline. None waits"), `MAX_COMMAND_BYTES=None`도 제거됨(`local_agent_oracle_mesh_executor.py:146`). 남은 것은 디스패치 TTL 600초(`oracle_mesh_read_return_routes.py:154`, 설계 문서가 lease 분리 후속으로 명시) → 유지. §3-2 |
| 5 | SNS 10MiB·8장 (#5872) | 1MB→10MiB 상향 반영·실측 완료(정책 §785). 엔진 Slack/Telegram 포트의 10MB는 **응답 읽기** 상한으로 별개(`slack_port_httpx.py:77`, `telegram_port_httpx.py:54`) — 유지. **사진 8장 상수는 코드에서 확인 못 함**(게시물 미디어 리사이즈 1920px만 확인, `photo-resize.js:19`) — 이슈 #5872 기준 유지. §3-5 |
| 6 | B66 10MiB (#5877) | 미리보기·키라/체험 파일럿 응답 10MB, PDF 32KB/32MB, 번들 32/48/20/10MB — #5877 상향분 실측 완료(정책 §784) → 유지. §3-4 |
| 7 | 웹 XLSX 인라인 10MB | `WEB_XLSX_INLINE_MAX_BYTES=10_000_000`(`workspace_storage.py:22`) — 총량은 1GiB(`:18`). 10MB 초과는 스트리밍 판정 경로로 자동 폴백(`:486-516`)이라 **실패는 없고** 인라인 파싱 메모리만 단위 → 빠른 개선 3번(50MB). §3-1 |
| 8 | 앞단 8초·30초·65초·120초 | 8초(일반 `worker.mjs:28`)/30초(API 읽기 `:29`·로그인 콜백 `:39`)/65초(apps AI `:190`) + tus 120초(`:34`). 역할이 분리돼 있고 실패 시 재시도·이어올리기가 있음 → 유지(tus만 여유 상향이 빠른 개선 5번). §3-6 |
| 9 | tus 90MiB·1GiB | **main 병합 완료**(#6584). 조각 90MiB(`tus_core.py:59`), 총량 1GiB(`:60`), 청소 24시간(`:79`), 브라우저 재개 단위 16MiB(`tus-upload.js:18`), 앞단 120초(`worker.mjs:34`). Cloudflare 무료 본문 약 100MB는 조각 경로로 우회됨. **사용자별 저장 용량 상한 없음 = 빈틈 D3** — tus_core는 소유자 스코프만 검증하고 총량 계산이 없음(코드 확인) → 유지 + D3 등재. §3-1 |
| 10 | 첨부 개수 | 코드는 **한 번에 1개**(`attachments.py:174-175` "현재는 파일을 한 번에 하나만") — tus 경로(`tus_chat_attachment.py`)도 같은 계약을 전제. 서버는 개당 1GiB까지 받으므로 다중화 여지 큼 → 상향(다중 첨부, UI+계약 동시 변경). §3-1 |
| 11 | 대화·메시지 길이 상한 | 임의 길이 상한 없음(브라우저 본문 무제한 — #4379/#5882 계열 정리 완료). 저장 미리보기 8,000자는 잘림 표시가 명시(`history.py:563-569`)라 유지, 조립 봉투 5.5MB(`history.py:15`)는 전송 6MB 아래 여유로 유지. §3-1 |
| 12 | 모델 입력 토큰 한도 | 고정 토큰 상한 없음 — 카탈로그 `context_window` × 비율(기본 0.60, 허용 0.2~0.9, `pc_context_budget.py:16-19`)로 압축 시작, 초과분은 아카이브+회수(#6460) — 임의 상한이 아니라 모델 보호 장치 → 유지. §3-7 |

## 4. 전체 상한 표

표 열: **위치(파일:줄) / 현재 값 / 누가 막히나(사용자 체감) / 바깥 한도와의 관계 / 권장 값**. 줄번호는 기준판 `5e741bce6` 기준.

### 4-1. Chat (COM2) — 업로드·대화·PC 결과

| 항목 | 위치(파일:줄) | 현재 값 | 누가 막히나(사용자 체감) | 바깥 한도와의 관계 | 권장 값 |
|---|---|---|---|---|---|
| tus 조각 상한 | `apps/padiem-chat/app/tus_core.py:59` (`PADIEM_TUS_CHUNK_MAX_BYTES`) · 브라우저 재개 단위 `static/tus-upload.js:18` | 90MiB(서버) / 16MiB(클라 조각) | 없음 — 조각 단위, 끊기면 이어올리기 | Cloudflare 무료 본문 약 100MB/요청 아래 여유 — **#6584로 main 병합, 엣지 한도 우회 완료** | 유지 |
| tus 총량 | `tus_core.py:60` (`PADIEM_TUS_MAX_UPLOAD_BYTES`) | 1GiB | 1GiB 초과 파일이 시작 시 거절 | R2 단일 PUT 5GiB·컴2 디스크 아래 정합. **사용자별 저장 용량 상한은 없음 = 알려진 빈틈 D3**(소유자 스코프만 검증, 총량 계산 부재 — 코드 확인) | 유지 + D3 등재(지시서 기준) |
| tus 미완성 청소 | `tus_core.py:79` (`PADIEM_TUS_CLEANUP_SECONDS`) | 24시간 | 없음 — 미완성 조각만 대상, 진행 중 업로드는 재개 윈도 | 컴2 디스크(여유 33GB) 고갈 방지와 균형 | 유지 |
| 채팅 첨부 개수 | `apps/padiem-chat/app/attachments.py:174-175` | 1개 | 여러 파일 동시 첨부 불가("한 번에 하나만") | 외부 한도 아님 — 자체 계약 | **상향(다중 첨부)** — UI 트레이+전송 계약 동시 변경 필요 |
| 첨부 크기 | `attachments.py:18` · `packages/padiem-ai-core/padiem_ai_core/b14_multimodal.py:13` · tus 경로 `tus_core.py:60` | 1GiB | 1GiB 초과 첨부 거절 | 컴2 디스크·전송 실한도와 정합(1차 정리로 1GiB화) | 유지 |
| 저장된 메시지 미리보기 | `apps/padiem-chat/app/history.py:14` (잘림 표기 `:563-569`) | 8,000자 | 없음 — 잘림을 화면에 명시, 전문은 공급자 기록으로 존재 | D1 행 2MiB와 무관(표시용) | 유지 |
| 대화 조립 봉투 | `history.py:15` (`MAX_MODEL_CONTEXT_BYTES`) | 5.5MB | 없음 — 초과분은 압축·아카이브로 진행 | 전송 봉투 6MB(`local_engine_transport.py:48`) 아래 여유 | 유지(봉투를 올릴 때 함께 재검토) |
| 대화 제목 | `history.py:16` | 80자 | 없음(표시) | 없음 | 유지 |
| PC 읽기 원본 총량 | `history.py:80` (`ORACLE_MESH_PC_READ_ORIGINAL_MAX_BYTES`) | 20MB | 20MB 초과 PC 읽기 원본이 Chat 단계에서 거절 | Cloudflare Worker 버퍼 잔재 — 외부 근거 없음 | **제거(4곳 묶음)** — #6460 출력 핸들·페이징으로 우회 완료 |
| 메시 본문(일반) | `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:164` | 6MB | 일반 폴 결과 6MB 초과 거절(큰 결과는 무제한 프레임으로 우회) | 구 전송 봉투 하위호환 | 유지 |
| 메시 결과 프레임 | `oracle_mesh_read_return_routes.py:163` | 무제한(None) | 없음 | — | 유지(회귀 금지) |
| 메시 presence 본문 | `oracle_mesh_read_return_routes.py:194` (항목 수 `:193`) | 8KiB | 없음(하트비트 프레임) | 프로토콜 프레임 | 유지 |
| 디스패치 TTL | `oracle_mesh_read_return_routes.py:154` | 600초 | 600초 내 미인출 명령 만료 → 재발급 | Cloudflare 시절 잔재 | 유지(lease 분리 후속 설계 대기 — 함부로 올리면 멱등성 해침) |
| PC 파일 읽기 상한 | `oracle_mesh_read_return_routes.py:3450` | 20MB | 20MB 초과 파일 직접 읽기 거절(페이징 경로는 가능) | Cloudflare 잔재 | **제거(4곳 묶음)** |
| 저장 본문 입력 | `apps/padiem-chat/app/saved_output_routes.py:19` | 96KB | 96KB 초과 저장이 413 거절 — 행 한도 2MB 아래 유일 병목 | D1 행 2MiB와 불일치 | **바로 변경: 96_000 → 2_000_000** |
| 저장 행 크기 | `apps/padiem-chat/app/saved_outputs.py:14` | 2MB | 2MB 초과 본문 거절 | D1 행 한도 2MiB와 일치 | 유지 |
| 저장 목록 페이지 | `saved_outputs.py:10` | 100 | 없음(페이지네이션, 개수 상한 아님) | — | 유지 |
| 웹 XLSX 총량 | `apps/padiem-chat/app/workspace_storage.py:18` (`MAX_WEB_XLSX_BYTES`) | 1GiB | 1GiB 초과 엑셀 거절(tus 경로 포함 `tus_web_xlsx_upload.py:53`) | 컴2 디스크·R2 여유 내 | 유지 |
| 웹 XLSX 인라인 | `workspace_storage.py:22` (`WEB_XLSX_INLINE_MAX_BYTES`, 사용처 `claw_web_xlsx_source_routes.py:38`·`tus_web_xlsx_upload.py:97`) | 10MB | 없음(실패 아님) — 10MB 초과는 스트리밍 판정 경로로 자동 전환(`:486-516`) | Cloudflare Worker 메모리 시절 잔재 추정 | **바로 변경: 10_000_000 → 50_000_000** (COM2 파싱 메모리 실측 1회 권장 — 실패 모드 없음) |
| 앱 AI 타임아웃 | `apps/padiem-chat/app/apps_ai.py:31` | 55초 | 55초 초과 생성 실패(앞단 65초 안에 끝남) | 앞단 65초(`worker.mjs:190`)와 정합 | 유지 |
| BYOK 응답 읽기 | `apps/padiem-chat/app/byok_client.py:39` | 10MB | 없음(비정상 대형 응답만 잘림 — 정상 스트림 소비) | 공급자 응답 버퍼 보호(무한 버퍼는 OOM 위험) | 유지 |
| BYOK 커스텀 모델 출력 토큰(이번 발견) | `byok_client.py:44` (`ANTHROPIC_MAX_TOKENS`) | 4,096토큰 | 긴 보고서 출력이 잘림(실패 아님·잘림 체감) | 공급자 모델별 출력 상한과의 정합 — **확인 못 함** | 유지(상향 검토 — 모델별 상한 확인 후) |
| 회의록 Drive 업로드 txt | `apps/padiem-chat/app/meeting_drive_upload_routes.py:30` | 10MB(txt) | 10MB 초과 회의 원문은 파일 레인(tus) 경로 안내 | 대형 문서는 파일 레인이 원칙 — 인라인 보조 경로 | 유지 |
| Drive 케이스 PDF | `apps/padiem-chat/app/drive_case_folder_engine.py:72` | 16MiB | 16MiB 초과 PDF는 파일 레인 경로 | 파서 입력 보호 | 유지 |
| 오피스 선택기 파일 | `apps/padiem-chat/app/claw_office_chooser_routes.py:63` | 10MB | 10MB 초과 문서는 파일 레인 경로 | 상동 | 유지 |

### 4-2. PC·메시 레인 (실행기 + 큐 + Chat + Engine — 4곳 연쇄)

| 항목 | 위치(파일:줄) | 현재 값 | 누가 막히나(사용자 체감) | 바깥 한도와의 관계 | 권장 값 |
|---|---|---|---|---|---|
| 실행기 읽기 봉투 | `apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py:147` | 20MB | 20MB 초과 PC 실행 결과가 실행기 전송 단계에서 거절 | Cloudflare Worker 버퍼 잔재(주석에 "older servers" 하위호환 명시) | **제거(4곳 묶음)** — 결과는 큐 출력 저장(파트 업로드)으로 감 |
| 실행기 조각 읽기 | `local_agent_oracle_mesh_executor.py:148` | 6MB | 없음(봉투 하위 단위) | 전송 봉투 | 유지(큐 파트 상향 시 함께 재검토) |
| 실행기 명령 본문 | `local_agent_oracle_mesh_executor.py:146` (`MAX_COMMAND_BYTES=None`) | 무제한 | 없음 | — | 유지(회귀 금지) |
| 실행기 presence 캐시 | `local_agent_oracle_mesh_executor.py:124` | 8대 | 8대 초과 기기 표시 밀림 | 메모리 | 유지(기기 수 증가 시 상향 검토) |
| 실행기 결과 거부 한도 | `local_agent_oracle_mesh_executor.py:167` | 3회 | 남용 결과 거부 3회 후 차단 | 보안상 필요 | 유지 |
| 실행기 폴링·백오프 | `local_agent_oracle_mesh_executor.py:58-60`, `:171-172` | 유휴 1→60초(COM2 10초)·백오프 5→60초 | 없음(폴링 리듬) | — | 유지 |
| 큐 내부 RPC 본문 | `apps/padiem-mesh-queue/internal_store.py:28` | 1MB | 없음(직접 실패 아님) — 21MB 출력이 21파트로 쪼개짐 | 큐는 컴2 로컬 서비스 — 외부 한도 없음 | **바로 변경: 1_000_000 → 8_000_000** (기존 1MB 발신자 하위호환) |
| 큐 메서드 이름 | `internal_store.py:29` | 64자 | 없음(폼) | — | 유지 |
| Engine PC 읽기 상한 | `apps/padiem-ai-engine/app/claw_pc_query_step_driver.py:119` | 20MB | 20MB 초과 원본 직접 전달 거절 — 모델은 `output_ref` 페이징을 씀(#6460) | Cloudflare 잔재(주석에 20MB 3곳 명시) | **제거(4곳 묶음)** |
| Engine PC 청크 | `claw_pc_query_step_driver.py:1182-1184` | 최대 1MB(기본 64KiB, `PADIEM_ENGINE_PC_CHUNK_BYTES`) | 없음(프로토콜 단위) | 청크 순서·무결성 검증 단위 | 유지 |
| Engine 검색 행 | `claw_pc_query_step_driver.py:908` | 50행 | 50행 초과는 스니펫 페이징으로 이어가기 | 응답 폭 | 유지 |
| PC 읽기 청크 요청 | `apps/padiem-chat/app/claw_pc_read_command.py:26` | 1MB | 없음 | 실행기 최대 청크와 일치하는 프로토콜 단위 | 유지 |
| PC 오피스 접두 읽기 | `claw_pc_read_command.py:35` · `claw_pc_search_command.py:34` | 16MiB | 없음(매직바이트 판별용 접두 — 상한 아님) | — | 유지 |
| PC 검색 스캔 | `claw_pc_search_command.py:29` | 2,000파일 | 2,000파일을 넘는 검색은 "이어가기"로 나눔 | PC 부담 보호 — no-deadline 설계가 10,000·페이징을 후속으로 명시 | 유지 |
| Tool 실행 마감 | `packages/padiem-ai-core/padiem_ai_core/tool_runtime.py:609-611` | 없음(None) | 없음 — #4379로 고정 300초 제거, None은 끝까지 대기 | — | 유지(방침 이행 상태) |

### 4-3. 전송·파서 (Chat↔Engine)

| 항목 | 위치(파일:줄) | 현재 값 | 누가 막히나(사용자 체감) | 바깥 한도와의 관계 | 권장 값 |
|---|---|---|---|---|---|
| Engine 일반(비모델) 요청 | `apps/padiem-chat/app/local_engine_transport.py:47` · 앱 AI 본문 `apps_ai.py:47,63,71` | 256KiB | 없음(소형 계약 전용) | — | 유지 |
| 오케스트레이션 모델 요청 | `apps/padiem-chat/app/worker_orchestration.py:45` | 6MB | 없음 — 구 256KiB는 5.5MB 봉투보다 작아 정정됨(주석 명시) | — | 유지(회귀 금지) |
| Engine 모델 경로 요청 | `local_engine_transport.py:48` | 6MB | 없음 — 조립 봉투 5.5MB 아래에서 처리 | Cloudflare 시절 모델 본문 한도 잔재 | 유지(재검토) — 큐 파트·5.5MB 조립과 묶음 재검토 |
| Engine 응답 읽기 | `local_engine_transport.py:49` · `worker_orchestration.py:41` | 10MB | 없음(비스트림 오류 응답만 대상 — 정상은 SSE 스트림) | 응답 버퍼 보호 | 유지 |
| 로컬 전송 타임아웃 | `local_engine_transport.py:72,75` | 30초 / 600초(스트림) | 스트림은 600초+진행 이벤트 — 고정 실패 아님 | 모델 유휴 예산 | 유지 |
| 스트림 오류 본문 | `local_engine_transport.py:77` | 64KiB | 없음(오류는 한계 JSON) | 프로토콜 | 유지 |
| 첨부 요청 파생 한도 | `local_engine_transport.py:57-58` | base64(1GiB)+8KiB | 없음(자동 파생) | `MAX_B14_IMAGE_BYTES` 연동 — 원 상수를 올리면 따라옴 | 유지 |
| 격리 파서 입력 | `packages/padiem-ai-core/padiem_ai_core/document_parser_boundary.py` | 수치 한도 없음(판정 모듈 — 본문 봉투 공유) | 없음 | #2824 격리 경계 — 파서 선정만 담당 | 유지(#5882 보류 목록 — 임의 변경 금지) |

### 4-4. B66 (견적)

| 항목 | 위치(파일:줄) | 현재 값 | 누가 막히나(사용자 체감) | 바깥 한도와의 관계 | 권장 값 |
|---|---|---|---|---|---|
| 인증 미리보기 | `apps/padiem-chat/app/b66_certified_preview.py:17` | 10MB | 10MB 초과 원문 미리보기 거절 | #5877 상향분 — 실측 완료(정책 §784) | 유지 |
| 키라·체험 파일럿 응답 | `b66_kira_direct_pilot.py:25` · `b66_experiential_direct_pilot.py:25` | 10MB | 상동 | 상동 | 유지 |
| 인증 PDF 요청/응답 | `b66_certified_pdf_routes.py:22-23` | 32KB / 32MB | 요청 32KB는 템플릿 지시 JSON — 실측됨 | — | 유지 |
| 견적 번들 | `b66_certified_quote_bundle.py:26-31` | 32/48/20/10MB·32멤버·압축비 1,000 | 정상 견적 영향 없음 — zip 폭탄 방지 | 보안(전개 폭발 방지) | 유지 |
| B66 대화 상태 | `b66_ai_conversation.py:56-65` | 1MB·8턴·20항목·메모 1,000자·프롬프트 4,000자 | 초과 입력은 접기 — 작업 실패 아님 | 실측된 대화 폭(임의 토큰 상한 아님) | 유지 |
| 가이드 초안 | `b66_guided_draft.py:20-24` | 1MB·80메시지·9,000자 | 상동 | 상동 | 유지 |
| PC 템플릿 요청 | `b66_pc_template_routes.py:46` | 4,000자 | 초과 요청 잘림 | 실측 폭 | 유지 |

### 4-5. SNS·커넥터

| 항목 | 위치(파일:줄) | 현재 값 | 누가 막히나(사용자 체감) | 바깥 한도와의 관계 | 권장 값 |
|---|---|---|---|---|---|
| Slack 응답 읽기 | `apps/padiem-ai-engine/app/slack_port_httpx.py:77` | 10MB | 없음(응답 읽기 버퍼 — 발송과 별개) | #5872 발송 10MiB 실측과 별개 항목 | 유지 |
| Telegram 응답 읽기 | `apps/padiem-ai-engine/app/telegram_port_httpx.py:54` | 10MB | 상동 | 상동 | 유지 |
| SNS 사진 개수 | **확인 못 함** | 8장(이슈 #5872 기준) | 9장째 사진에서 거절로 추정 — 코드 상수 위치 **확인 못 함** | 공급자 기준 — **확인 못 함** (게시물 미디어 리사이즈 1,920px만 확인, `photo-resize.js:19`) | 유지(이슈 기준) — 상수 위치 확인이 남은 과제 |
| Slack 채널 나열 | `packages/padiem-ai-core/padiem_ai_core/slack_capability.py:72` | 128 | 128개 초과 채널은 허용 목록에 넣을 수 없음 | Slack API와 무관한 자체 조회 폭 | 유지 |
| 커넥터 PC RPC | `apps/padiem-chat/app/connector_native_pc_gateway_port.py:31`(30초) · `connector_pending_pc_owner_rpc.py:32`(20초) · `canonical_connector_enrollment_async_host.py:33`(15초) · `connector_owner_identity_pc_completion.py:31`(10초) · `connector_pending_pc_offer_gateway.py:25-27`(10/8초·8KiB) · `com2_pc_offer_relay.py:16`(8KiB) | 30/20/15/10/8초 · 프레임 8KiB | 연결 수립 지연 시 그 단계만 재시도 — 파일 전송 아님 | 신호 교환 프레임(대용량은 파일 레인) | 유지 |
| 로컬 연결 검사 | `apps/padiem-chat/app/claw_local_connect_composition.py:55` | 10초 | 느린 PC의 최초 연결 검사 실패 가능(재시도 있음) | — | 유지 |
| 큐 프록시 타임아웃 | `apps/padiem-chat/app/queue_store_proxy.py:40` | 8초 | 큐 지연 시 프록시 오류(상위 재시도) | — | 유지 |

### 4-6. 앞단 (Cloudflare Worker)

| 항목 | 위치(파일:줄) | 현재 값 | 누가 막히나(사용자 체감) | 바깥 한도와의 관계 | 권장 값 |
|---|---|---|---|---|---|
| 일반 쓰기·읽기 | `apps/padiem-chat-front/worker.mjs:28` | 8초 | 없음 — 죽은 업스트림 판별용, 장기 작업은 전용 경로(tus 120초·apps AI 65초) | — | 유지 |
| API 읽기 | `worker.mjs:29` | 30초 | 30초 초과 목록·조회 실패(멱등 — 재시도) | — | 유지 |
| 로그인 콜백 | `worker.mjs:39` | 30초 | OAuth+JWKS+identity RPC 지연 시 실패 | worker.mjs 주석의 운영 교훈 근거 | 유지 |
| apps AI | `worker.mjs:190` | 65초 | 65초 초과 모델 응답 실패 — Chat 측 55초와 정합 | Cloudflare 무료 CPU 기준(프록시는 영향 없음) | 유지 |
| tus 조각 | `worker.mjs:34` (`DEFAULT_TUS_TIMEOUT_MS`) | 120초 | 90MiB를 120초에 못 올리는 회선(≈750KB/s 미만)에서 조각 재시도 — 이어올리기로 회복 | Cloudflare 무료 본문 약 100MB 아래 | **바로 변경: 120000 → 180000** (프록시 타임아웃 연장만 — 실패 모드 동일) |

### 4-7. 모델·에이전트 (Engine/Core/kagent)

| 항목 | 위치(파일:줄) | 현재 값 | 누가 막히나(사용자 체감) | 바깥 한도와의 관계 | 권장 값 |
|---|---|---|---|---|---|
| 컨텍스트 압축 시작 비율 | `apps/padiem-ai-engine/app/pc_context_budget.py:16-19` | 0.60 (허용 0.2~0.9) | 없음(모델 보호 장치) | 카탈로그 `context_window` 기준 — 임의 상한 아님 | 유지 |
| 최소 압축 예산 | `pc_context_budget.py:21` | 2,048토큰 | 없음(하한 보장) | — | 유지 |
| 추가 시스템 컨텍스트 | `apps/padiem-chat/app/b14_client.py:50` | 무제한(None) | 없음 | — | 유지(회귀 금지) |
| B14 이미지 | `packages/padiem-ai-core/padiem_ai_core/b14_multimodal.py:13` | 1GiB | 1GiB 초과 이미지 거절 | 컴2 디스크 정합 | 유지 |
| 체크포인트 단계·스윕 | `apps/padiem-ai-engine/app/agent_durable_d1.py:25,30-31` | 64단계 · 스윕 500/2,000 | 없음(하우스키핑) | D1 저장소 청소 파라미터 | 유지 |
| 에이전트 정의 폭 | `packages/padiem-ai-core/padiem_ai_core/agent_definition.py:27-34` | 제목 160·설명 1,000·지침 12,000자 등 | 폼 초과 입력 거절(작업 실패 아님) | 폼 유효성 | 유지 |
| 승인 창 | `packages/padiem-ai-core/padiem_ai_core/agent_approval.py:25` | 24시간 | 24시간 지난 승인 만료 | 보안상 필요 | 유지 |
| durable lease | `packages/padiem-ai-core/padiem_ai_core/agent_durable_lease.py:26-27` | 1~3,600초 | 없음(잠금 설계) | — | 유지 |
| 에이전트 이벤트 폭 | `packages/padiem-ai-core/padiem_ai_core/agent_events.py:10-12` | 1,000자·키 16·ID 128 | 초과 이벤트 잘림 | 로그 폭 | 유지 |
| 계획 폭 | `packages/padiem-ai-core/padiem_ai_core/agent_planner.py:22-25` | 32단계·목표 1,000·입력 32,000자 | 초과 계획 거절 | 계획기 입력 폭 | 유지 |
| kagent 아티팩트 | `apps/korean-ai-code-agent/src/kagent/artifact_registration.py:50` | 8MB | 8MB 초과 산출물은 PC 출력 저장 핸들 경로(정규 경로) | 스냅샷 폭 | 유지(검토) |
| kagent 도움 요청 TTL | `apps/korean-ai-code-agent/src/kagent/agent_human_control.py:12` | 600초 | 10분 내 미승인 시 만료(재요청 가능) | 보안·운영 | 유지 |
| 브라우저 임대 | `apps/korean-ai-code-agent/src/kagent/browser_control_actions.py:93-96` | 300/900초 · 25/100행동 · 유휴 120초 | 임대 초과 작업은 재임대 | 최소권한 — 보안상 필요 | 유지 |
| 인증 남용 한도 | `apps/padiem-chat/app/auth_abuse.py:13-16` · `auth_routes.py:602-606` | 5/50/10,000회 · 잠금 60분 | 반복 실패 계정 일시 잠금(무기한 아님) | 보안상 필요 | 유지 |
| 관리·인증 소폼 | `account_model_selection_routes.py:35`(256B) · `platform_admin_routes.py:37`(1KB) · `android_device_enrollment_routes.py:35`(4KB) · `android_auth_routes.py:64,68`(8KB·128자) | 256B~8KB | 없음(폼) | 폼 유효성 | 유지 |

### 4-8. 의원3종 (council)

| 항목 | 위치(파일:줄) | 현재 값 | 누가 막히나(사용자 체감) | 바깥 한도와의 관계 | 권장 값 |
|---|---|---|---|---|---|
| 생성 대기 | `apps/padiem-council-apps/static/council-app.js:90` (사용 `:203`) | 120초 | 120초 초과 긴 생성이 **시간으로 사망**(방침 위반 소지) | 외부 한도 아님 — 자체 타이머(`util-menu.js`에는 타이머 없음, `:200` 주석은 옛 설명) | **바로 변경: 120000 → 300000(임시 완화)** — 근본은 진행 중+경과 표시 전환(단일 파일) |
| 사진 리사이즈 | `apps/padiem-council-apps/static/photo-resize.js:19` | 1,920px | 없음(표시 품질·메모리) | 게시물 미디어 실측 크기와 일치 | 유지 |

## 5. 외부 한도 — 우리가 못 바꾸는 것 (표기 전용)

| 한도 | 값 | 영향 |
|---|---|---|
| Cloudflare 무료 요금제 본문 | 약 100MB/요청 | tus(90MiB 조각, #6584 병합)으로 업로드 주 경로의 엣지 한도 우회 **완료** — 소형 JSON 경로는 100MB 아래 사용 |
| D1 행 크기 | 2MiB | 프로젝트 파일 추출 텍스트·저장 행(2MB)이 여기에 정합 |
| R2 단일 PUT / 멀티파트 | 5GiB / 10,000파트 | 1GiB 원본 저장에는 여유 |
| Slack·Telegram 공급자 | 공급자 기준 | 발송 10MiB는 #5872 실측으로 공급자 기준 확인 완료 |
| COM2 디스크 | NVMe 128GB(여유 33GB)·HDD 2TB | tus 총량 1GiB·출력 저장의 실한도 — 여유 모니터링 필요 |
| systemd ProtectSystem=strict | 기록 경로 제한 | tus 임시 디렉터리는 허용 경로만 사용(운영 문서 §8-1) |
| Cloudflare Worker 자원 | CPU/메모리 | 파일 파싱·PC 결과 버퍼링은 컴2 이전으로 우회 — 잔여 경로는 원冻结(파일 레인 문서 기준) |
| (자체 빈틈, 외부 아님) 사용자별 저장 용량 상한 | 없음 | **알려진 빈틈 D3** — tus 3레인 모두 총량 1GiB/업로드만 있고 사용자별 누적 용량 계산이 없음(`tus_core.py` 소유자 스코프만 검증). 컴2 디스크가 유일한 실한도 |

## 6. 레인 배정 제안

- **아스트라(한 곳짜리)**: ① 저장 본문 96KB 정렬(Chat 단일, 빠른 개선 1번) ② 웹 XLSX 인라인 50MB(빠른 개선 3번) ③ 의원3종 생성 진행 표시(council 단일 — 300초 임시 완화는 그때 회수) ④ 채팅 첨부 다중화(Chat 서버+화면)
- **컴1 로컬(여러 서비스 연쇄)**: ① PC 읽기 20MB 4곳(실행기·Engine·Chat·history) — 출력 핸들 우회 완성 후 상한 제거 ② 6MB 봉투·큐 파트 재검토(실행기·큐·Chat·로컬 전송) — 큐 8MB(빠른 개선 2번)부터 단계 적용
- **유지·감시 대상**: tus 90MiB/1GiB(병합 완료 — 배포 후 엣지 413 소멸 실측)·빈틈 D3(사용자별 용량 상한)·B66 실측값·Engine 포트 응답 10MB·인증 남용 한도

## 7. 참조

- docs/architecture/PC_LANE_NO_DEADLINE_DESIGN_20261026.md — 고정 마감 폐지 설계(20MB 경계·200개 페이지·10,000개 탐색·ToolSpec 300초·_DISPATCH_TTL 600초 후속)
- docs/architecture/FILE_LANE_COM2_MIGRATION_20261026.md — 1차 걷어내기(#5872/#5875/#5877/#5862/#5876)와 물리 한도표
- docs/research/LARGE_UPLOAD_1GB_DESIGN_20261101.md — tus A안(90MiB·1GiB 근거)
- docs/architecture/PADIEM_PC_REMOTE_LIMITS_WIRING_6460_20261101.md — #6460 §5-1 출력 저장·컨텍스트 압축 배선
- docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md §784-785 — B66·SNS 실측 상태
- docs/operations/PADIEM_MODEL_CONTEXT_FIDELITY_20261012.md — 14k/16k/32k 임의 컨텍스트 상한 제거·5.5MB 봉투 근거
- docs/operations/CPYTHON_P01_ENGINE_TRANSPORT_20261031.md — 로컬 전송 본문 한도(256KiB/6MB/10MB)
- 이슈: #6460(4번) · #5882(A 목록 정본) · #6579~#6584(tus, main 병합 `142bcc082`) · #5872 · #5877 · #4379 · #5573 · #5881
