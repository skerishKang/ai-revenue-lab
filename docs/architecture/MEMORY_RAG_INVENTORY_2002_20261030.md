# #2002 기억·검색(RAG) 현황표와 Vector DB 필요성 판단

- 작성: 2026-10-30, 아스트라5 레인(조사·로컬 실측·문서 작성 전용). 코드·설정·자원 변경 없음, 배포 없음, 머지 없음.
- 기준선: `main` = `d1eea300b01f5e76db32cf48e340a22981c4d490`. 읽은 근거는 이 리비전의 파일이다.
- 읽은 지시: 저장소 루트 `AGENTS.md`, 이슈 #2002 본문 + 댓글 4개(2026-10-25 CENTRAL 정합화 반영), #5151(C안), #2409(책임 경계).
- 금지 준수: Vector DB·Vectorize·새 D1·새 서비스 생성 없음, 운영 데이터 조회 없음, 운영 배포·설정 변경 없음, 자격증명 회수 사용 없음(공개 저장소 익명 클론), 사용자 데이터·비공개 사업 자료 미포함.

## 0. 결론 먼저

```text
NEW_VECTOR_DB_REQUIRED=NO_NOT_AT_THIS_STAGE
FIRST_MISSING_TIER=LEXICAL_SEARCH_INDEX_NOT_BUILT
AVAILABLE_IN_EXISTING_STORE=YES_D1_FTS5_OFFICIALLY_SUPPORTED
PROVISIONED=NO_CHANGE
IMPLEMENTED=NONE_IN_THIS_ISSUE
OWNER_DECISION=ONE (search를 제품 기능으로 올릴지 — §7)
```

- 신규 Vector DB는 **현 단계에서 불필요**로 판단한다. 근거는 §6에 3개로 정리했다.
- 지금 실제로 없는 것은 벡터 저장소가 아니라 **어휘(토큰) 검색 인덱스**다. 그 어휘 검색은 기존 D1에서 공식 지원한다.
- 의미검색이 제품 요구로 확인되면 그 시점에 §5의 옵션 비교로 재평가한다. 재평가 조건을 §6-마지막에 적었다.

## 1. 현황표 (inventory)

열의 의미를 분리해 적었다. **구현** = 코드가 존재하는 위치. **운영 연결** = 라우트·바인딩이 실제로 배선되어 있는지. **실사용 검증** = 사람이 쓰는 경로에서 동작 증거가 기록되어 있는지. 코드가 있다는 것만으로 운영 동작이라 쓰지 않는다.

판정: `PRESENT` 요구가 구현되어 있음 / `PARTIAL` 일부만 / `GAP` 구현 없음 / `NOT VERIFIED` 배선은 보였으나 실사용 증거 없음.

### 1-1. Chat (apps/padiem-chat)

| # | 기능 | 구현 | 운영 연결 | 실사용 검증 | 판정 |
|---|---|---|---|---|---|
| 1 | 대화 기록 저장 | `app/history.py:775` `D1HistoryStore`, `append_exchange :1415` / 테이블 `conversations`·`messages` `migrations/001_auth_history.sql:18,29` | D1 `PADIEM_CHAT_DB` `wrangler.toml:246-249` | 저장·복원 라우트 테스트 `tests/test_auth_history.py:279-303` | PRESENT |
| 2 | 대화 기록 검색 | `history.py:1270` `search_conversations` — `LIKE ? ESCAPE '\'` 부분문자열, 질의 80자·결과 20건·대화당 최근 2000행 창(`:17-23`) | `GET /api/conversations/search` `app/app_factory.py:669`, UI `static/conversation-search.js:17` | 스토어 단위만(실제 sqlite `tests/test_b66_conversation_isolation_4657.py:121,127`). HTTP→D1 종단은 없음. 라우트 존재는 소스 grep(`test_4471_conversation_search.py:146-148`) | PARTIAL |
| 3 | 문서 저장 | `app/project_files.py:447` `create_file` / 테이블 `project_files` `migrations/003_project_files.sql:4`, 본문 1행 2MiB 상한 `migrations/077_...sql:42` | 같은 D1 + R2 `PADIEM_WORKSPACE_FILES` 원본 키 `app/project_file_routes.py:36` | `tests/test_5115_project_files_extracted_schema.py:152`, `test_5734_project_file_schema_bound.py:67` | PRESENT |
| 4 | 문서 검색 | 이름·국가·종류 메타데이터만: `list_owner_files :343`, `find_current_by_name :388`(이름 완전 일치 + `doc_kind`) | 라우트 `app/project_file_routes.py` 목록·상세 | 목록·저장 테스트 있음 | PARTIAL — 본문(`content_text`)을 검색하는 라우트 자체가 없음 |
| 5 | 첨부 컨텍스트 | `app/attachments.py:167,175` 1턴 1첨부, `app/documents.py:170` `build_document_context` | 첨부 파싱은 `parse_attachments :117` | `tests/test_2824_chat_binary_document_context.py:135-188` (PDF/DOCX/PPTX/XLSX 본문이 모델 컨텍스트에 도달) | PARTIAL — 턴 안에서만 유효, 첨부 본문은 저장·재검색되지 않음 |
| 6 | 사용자·tenant 권한 필터 | `_require_product_scope history.py:164`, 목록·검색·상세·삭제·추가 전부 `user_id`+`product_scope` 바인드(`:1261,1292,1329,1350,1428`) | `auth_ready`+`current_user_id` → 401 `app/conversation_routes.py:16-18` | 격리 테스트 실sqlite로 통과(`4657:102-205`) | PRESENT, 단 아래 §3-나 열거의 scope 누락 경로 3종 |
| 7 | 전문(FTS) 인덱스 | 없음 — migration 78개 중 `CREATE VIRTUAL TABLE` 0개(§4 재현 실행에서 78/78 적용, FTS 구문 0) | 없음 | 없음 | GAP |
| 8 | 임베딩·의미검색 | 없음 | 없음 | 없음 | GAP |

### 1-2. Claw (기억)

| # | 기능 | 구현 | 운영 연결 | 실사용 검증 | 판정 |
|---|---|---|---|---|---|
| 9 | 승인 기억 저장 | `app/approved_memory.py` 테이블 `claw_approved_memory` `migrations/011_...sql:1`, 최대 30건·120/500자(`:29`) | `app_factory.py:857-860` 4개 라우트, D1 바인딩 있을 때만 구성(`:1542`) | 라우트·스토어 테스트 존재 | PRESENT |
| 10 | 기억 → 모델 프롬프트 주입 | **없음.** `approved_memory_store`의 실제 소비자는 `app_factory.py:1548`와 `claw_memory_routes.py:124`뿐 — 컨텍스트·프롬프트·grounding 빌더에 등장하지 않음 | 배선 없음 | 없음 | GAP |
| 11 | 기억 검색 | `list_approved_memories :220` = `ORDER BY created_at DESC LIMIT` 뿐 | 라우트 있음 | 없음 | GAP |
| 12 | Claw 실행 기록 | `record_claw_run`/`list_recent_claw_runs history.py:1818-1841` | 라우트 있음 | 있음 | PRESENT (정확 키 조회만) |
| 13 | `apps/padiem-chat-claw-native`, `packages/padiem-embedded-runtime`의 기억 | 코드 없음(검색 결과 0) | 없음 | 없음 | GAP |

### 1-3. B66

| # | 기능 | 구현 | 운영 연결 | 실사용 검증 | 판정 |
|---|---|---|---|---|---|
| 14 | B66 대화 저장 | `app/b66_ai_conversation_store.py:37-38,74,136` `(user_id, workspace_id)` 키, `state_json` 서버 소유 | 라우트 있음 | 격리 테스트 `test_b66_conversation_isolation_4657.py` | PRESENT |
| 15 | B66 대화 검색 | `b66_dialogue_routes.py:100` 목록-또는-검색(`:129`에서 `store.search` 호출) | `app_factory.py:775,776` | 라우트 레벨 증거 없음 | NOT VERIFIED |
| 16 | B66 문서·견적 자산 | 변환 작업/항목 `migrations/066_document_convert_jobs.sql:6,19`(page_count·character_count·markdown_key), 번들 R2 `apps/b66-pdf-renderer/bundle.py:54` | 배선 있음 | 스키마·저장 테스트 | PRESENT(저장) / 본문 색인 없음 |
| 17 | B66 텍스트 추출 | `apps/b66-quote-adapter/app/extraction_routing.py:168`가 `text_extraction_model_pending`로 fail-closed | 배선 있음 | 실패 경로가 계약 | PARTIAL |

### 1-4. Core (packages/padiem-ai-core)

| # | 기능 | 구현 | 운영 연결 | 실사용 검증 | 판정 |
|---|---|---|---|---|---|
| 18 | 검색 계약 | `padiem_ai_core/retrieval.py` `RetrievalRequest/RetrievedItem/RetrievalProvider(:229)/prepare_retrieval_context(:327)` | 저장소 미실현(모듈 문서 `:1`이 벡터 DB·RAG 청크를 명시적으로 범위 밖으로 선언) | 없음 | PARTIAL — 계약만 |
| 19 | 기억 쓰기/읽기 계약 | `memory.py`(scope·provenance·write authorization), `memory_read.py:113` `authorize_memory_retrieval`, `memory_receipt.py`, `memory_context.py:72` `rank_retrieval_results` | 저장소 미실현 | 없음 | PARTIAL |
| 20 | 구체 `RetrievalProvider` 구현체 | **없음.** 재고 전체에서 생산 구현체 0, 테스트 페이크만(`apps/padiem-ai-engine/tests/test_memory_retrieval_service.py:42`) | 없음 | 없음 | GAP |
| 21 | `assemble_long_context`·`MemoryWriteAdapter` 소비자 | 패키지 밖 소비자 0 | 없음 | 없음 | GAP(미사용 이음매) |
| 22 | 문서 세그먼트 | `document_semantics.py:206` `DocumentSegment`, 상한 40,000자·512세그먼트(`:29,30`) | 전송 전용 — 영속화 없음 | `drive_case_pdf_browser_bridge.py:222,230`에서만 사용 | PARTIAL |

### 1-5. Engine (apps/padiem-ai-engine)

| # | 기능 | 구현 | 운영 연결 | 실사용 검증 | 판정 |
|---|---|---|---|---|---|
| 23 | `memory_rag` capability | `capability_manifest.py:536` **DEFERRED**, `contract_manifest.py:232` DEFERRED | `worker.py:314-328` `_memory_service_for_env`가 빈 bindings로 구성 → 항상 `memory_binding_unavailable` 503 | 실패가 계약인 테스트(`test_engine_canonical_composition_runtime.py:197`, `tests/test_production_composition_conformance.py:513`) | NOT VERIFIED — E9 A4는 `docs/operations/E9_ACTIVATION_PLAN.md:45,69`에서 지금까지 미활성 |
| 24 | Engine 문서 바이트 저장 | `app/document_byte_store.py:76` 보존 7일 | D1 6개 + R2 | 있음 | PRESENT(보존·회수용, 검색 아님) |

### 1-6. 집계

| 판정 | 개수 |
|---|---|
| PRESENT | 8 (#1,3,9,12,14,16,24, 그리고 #6) |
| PARTIAL | 8 (#2,4,5,16은 저장 한정, #17,18,19,22) |
| GAP | 7 (#7,8,10,11,13,20,21) |
| NOT VERIFIED | 2 (#15,23) |

## 2. 요구 분리 (이슈 §조사 2)

| 요구 | 현재 충족 | 실제로 빠진 기능 |
|---|---|---|
| 가. 키워드·메타데이터 필터 검색 | **부분 충족.** 대화는 부분문자열 LIKE + 최근 2000행 창 + 20건 상한. 문서는 이름/국가/종류 메타데이터 조회만 | 토큰화 인덱스 없음, 관련도 랭킹 없음, 문서 본문 검색 라우트 없음, 결과 상한 초과 시 조용히 잘림(§4에서 131건 실측), 오래된 매칭 누락(§4에서 실측) |
| 나. 임베딩 기반 의미검색 | **미충족.** 재고 전체에 임베딩 생성·저장·유사도 계산 코드 0 | 임베딩 생성 경로, 벡터 보존, 유사도 질의, 결과 랭킹 전부. 단 요구 자체가 제품에서 확인되지 않음(#2002가 "필요한 경우에만"을 전제) |
| 다. 대화 기억 | **부분 충족.** 저장은 D1+R2에 견고하게 있음. 승인 기억은 저장·표시까지 있음 | "기억"의 제품 동작(과거 대화를 새 대화에 되살려 주입)이 없음 — §1-2 #10. 요약·압축도 없음(잘림만) |
| 라. 문서 청크 색인·재색인 | **미충족.** 세그먼트는 요청 전송 중에만 존재하고 어디도 영속되지 않음 | 청크/지단 테이블 0, 재색인 개념 0, 색인-원본 정합성 보장 0 |

## 3. 추가 확인된 사실 두 가지

- 가. **D1의 LIKE 패턴 한도와 코드 상수의 불일치(운영 미검증 위험).** 공식 D1 한도는 `LIKE`/`GLOB` 패턴 **50바이트**이다([D1 Limits](https://developers.cloudflare.com/d1/platform/limits/), 2026-10-24판). 이 저장소의 대화 검색은 질의를 **80자**까지 받아 `%needle%`를 만든다(`history.py:17-23,1287-1297`). 한국어는 1자 3바이트라 **17자 질의부터 패턴이 53바이트로 초과**한다(16자 = 정확히 50바이트). 같은 저장소는 이 한도를 이미 알고 다른 경로에서 우회했다 — `history.py:2131-2145`가 "D1 rejects a LIKE pattern longer than 50 characters" 주석과 함께 `LIKE`를 버리고 `substr()` 접두 비교로 바뀌어 있다. 대화 검색 경로는 그 우회를 적용받지 않았다. **판정: 확인 필요(운영에서 질의 한 번으로 입증되지 않았고, 이 조사는 운영을 호출하지 않았다).**
- 나. **scope 누락 3종(보안 결함으로 단정하지 않음).** `product_scope`가 붙지 않는 읽기·갱신: `verify_owner_conversation_artifacts history.py:1843-1854`, `register_owner_conversation_artifact :1921-1930`, `UPDATE conversations SET updated_at ... WHERE id=? AND user_id=?` 7곳(`:1476,1552,1664,1727,2388,2474,2592`). `user_id`는 붙어 있으므로 교차 계정 노출이 아니라 **같은 사용자의 제품 간(B62/B66) 경계 누락** 가능성이다. 메시지 하위 읽기는 부모 대화 검증을 통과해야 도달한다(`:1334,1356,1029`).

## 4. 로컬 합성 실측 (이슈 §조사 3)

운영 데이터·운영 D1은 쓰지 않았다. 합성 문장만 쓴 throwaway in-memory sqlite이고, 계측 대상은 **출하된 코드 그 자체**다(`D1HistoryStore.search_conversations`, `D1ProjectFileStore`) — 저장소 자신의 격리 테스트가 쓰는 D1 형태 퍼사드(`tests/test_b66_conversation_isolation_4657.py:33-56`)를 그대로 재사용했다. 네트워크·D1 요청 오버헤드는 이 측정에 없다.

- 환경: Python 3.13.7, SQLite 3.50.4, **migration 78/78 적용 실패 0**, 로컬 FTS5 사용 가능
- 규모: 대화 321개 / 메시지 4,644건 + 문서 60건, 전부 합성
- 재현: 이 레인의 `work/measure_keyword_retrieval.py`(저장소 밖, 커밋 안 함). 결과는 `work/measure_result.json`

### 가. 키워드 검색 정확도 (합성 코퍼스에서 참값 기지 대비)

| 질의 형태 | 결과 | 해석 |
|---|---|---|
| A1 정확한 부분문자열 | 20건 (0.32ms) | 상한 20에 닿음 |
| A2 단어 순서 바뀜 (`축제 마을`) | **0건** | 부분문자열이라 순서 필수 |
| A3 같은 대화 안 분리 출현 (`축제 안전`) | **0건** | 근접 질의 불가 |
| A4 오탈자 1자 (`축게`) | **0건** | 퍼지 매칭 없음 |
| A5 표기 변형 (`축제 행사`) | **0건** | 동의어/형태소 없음 |
| A6 공백만 | 0건 (문 실행 안 함) | 의도된 가드 |
| A7 80자 초과 | 80자로 잘려 0건 | 절단 규칙 `:287-292` |
| B1 매칭 151개 중 | **20개만 반환, 131개 소실** | 최근순 정렬이라 관련도 높은 오래된 대화가 잘림 |
| B2 2,204번째 메시지 대화의 1번째 메시지 매칭 | **0건 (누락)** | 대화당 최근 2,000행 창 밖 |
| C1 다른 계정 동일 질의 | 겹침 0 | 격리 유지 |

### 나. 지연 (같은 질의 5회 반복 중앙값)

| 코퍼스 크기 | 중앙값 |
|---|---|
| 대화 300 / 메시지 4,596 | 0.65ms |
| 대화 200 / 3,796 | 0.62ms |
| 대화 100 / 2,996 | 0.60ms |
| 대화 50 / 2,596 | 0.61ms |

로컬 기준으로는 규모가 작 때 지연이 문제가 아니다. 실제 병목은 재현율(위 B1·B2)이다. 운영 D1는 DB 1개가 단일 스레드로 쿼리를 직렬화하고 요청당 오버헤드가 있다([D1 Limits FAQ](https://developers.cloudflare.com/d1/platform/limits/)) — 이 측정은 그 값을 포함하지 않으므로 운영 지연 대리로 쓰지 말 것.

### 다. 같은 코퍼스에 FTS5를 물렸을 때 (측정 도구일 뿐, 제안 아님)

| 질의 | LIKE | FTS5(토큰) |
|---|---|---|
| A1 정확한 구 | 20 | 30 행 매칭 |
| A2 순서 바뀜 | 0 | **30** |
| A3 분리 출현 | 0 | 0 (행 내 동시 출현 필요) |
| A4 오탈자 | 0 | 0 |
| 지연 | 0.6ms | 0.01–0.06ms |

FTS5는 A2를 고치고 A4는 고치지 못한다. 한국어 형태소 분석은 기본 토크나이저로 안 되는 영역이므로, 어휘 인덱스를 올리더라도 한국어 품질은 별도 검증 항목이다.

### 라. 문서 메타데이터 검색

- `list_owner_files` 60건 0.27ms, 본문 컬럼 미포함(`carriesContentText=false`) — 목록 설계는 정상
- `find_current_by_name` 완전 일치 → 발견(0.04ms), 부분 문자열 → 미발견(설계상 조회이지 검색이 아님)
- 본문에 목표 구문을 가진 행 8건이 DB에 존재하나 **본문을 검색하는 라우트가 없음**

## 5. 옵션 비교 (의미검색이 실제로 필요해진 경우에 대비)

판단 유보 상태에서 조건만 정리한다. 비용 수치는 이 조사에서 사용한 공식 페이지에 나와 있지 않은 것을 추정해 쓰지 않았다.

| 축 | A. 기존 D1 확장 (FTS5 + 필요시 임베딩 컬럼) | B. Cloudflare Vectorize | C. 외부 관리형 벡터 서비스 |
|---|---|---|---|
| 새 자원 | 없음(같은 DB에 테이블·마이그레이션 추가) | Vectorize 인덱스 1개 = **새 자원 → 대표 결정 필요** | 계정·계약·시크릿 신규 |
| 데이터 위치 | 기존 D1과 동일. 원본과 한 곳이어서 색인-원본 정합성 유지가 쉬움 | Cloudflare 전역 분산. 메타데이터 10KiB/벡터, 1,536차원 float32, 인덱스당 2,000만 벡터([Limits](https://developers.cloudflare.com/vectorize/platform/limits/), 2026-08-05판) | 공급사 리전 선택·계약 필요 |
| 격리 | `user_id`/`product_scope`/`country`를 같은 SQL에서 계속 사용 — §3-나 경계 규칙 재사용 가능 | namespace(무료 1,000 / 유료 50,000)·metadata로 재현 가능하나 **tenant 키를 두 저장소에 이중 보존**해야 함 | 별도 접근 통제 설계·증명 필요 |
| 지연 | §4-나 기준 재현율 문제가 우선. D1 단일 스레드 직렬화가 동시성 상한 | 공식 문서에 쿼리 지연 수치 미확인(이 조사에서 확인한 페이지들) → **미확인** | 미확인 |
| 유지관리 | 마이그레이션 1개 + 기존 백업 경로(§ `COM2_OFFSITE_BACKUP_RUNBOOK.md:56-66`)에 자동 포함 | 임베딩 생성·재색인·삭제 연동·보존 정책·백업이 **별도 계층**으로 추가 | 동일 + 공급사 장애·이전 리스크 |
| 비용 | 저장소 추가 없음. D1 무료 한도(500MB/DB) 안 — 실측 기록상 chat 1.5MB / engine 0.3MB(`CLOUDFLARE_ASSET_RECOVERY_AND_SYNC_20261019.md:247,252-255`) | 단가 표는 이 조사에서 확인한 페이지에 없음 → **추정도 쓰지 않음. 공식 pricing 확인 필요** | 미확인 |
| 스키마 리스크 | D1 행 2MB 한도(공식)와 같은 DB를 공유하므로 임베딩 대량 추가 시 한도 재계산 필요 | 없음(별도 저장) | 없음 |

## 6. Vector DB 필요성 결론과 근거

**결론: 불필요(현 단계).** 근거 3개:

1. **없는 계층이 벡터가 아니라 어휘다.** §4-가에서 실패의 전부(순서·분리·오탈자·상한 절단·창 누락)는 임베딩이 아니라 토큰 인덱스와 랭킹으로 잡히는 실패다. FTS5는 기존 D1에서 공식 지원한다([D1 SQL statements](https://developers.cloudflare.com/d1/sql-api/sql-statements/), 2026-04-21판: "D1 supports a subset of SQLite extensions … including: FTS5 module for full-text search (including fts5vocab)"). 새 자원 없이 마이그레이션과 스토어 함수로 도달 가능한 계층을 건너뛰고 Vector DB를 두는 것은, #2002가 금지한 "특정 Vector DB를 선결조건화"에 해당한다.
2. **규모가 저장소 선택을 강제하지 않는다.** 운영 D1 실측 기록이 chat 1.48MB / engine 0.3MB이고(`docs/operations/CLOUDFLARE_ASSET_RECOVERY_AND_SYNC_20261019.md:247,252-255`), D1 한도는 DB당 10GB(유료). 지금 병목은 재현율과 배선 부재지 처리량·저장 용량이 아니다.
3. **기억 기능의 결함은 저장소가 아니라 단절이다.** 승인 기억은 이미 저장·격리·REST 노출까지 되어 있고(`approved_memory.py`, `claw_memory_routes.py`) 프롬프트에 주입되는 경로가 없어 사용자 입장에서 "기억 안 함"으로 보인다(§1-2 #10). 새 저장소를 사도 그 배선이 있어야 동작한다. 반대로 새 저장소 없이도 동작한다.

**재평가 조건(의미검색이 진짜 필요해지는 시점):** (a) 대표가 대화·문서 검색을 제품 기능으로 올려 어휘 품질 요구가 확인되고, (b) §7 후속 이슈의 어휘 인덱스 도입 후에도 재현율이 요구에 못 미치며, (c) 임베딩 생성·보존·재색인·삭제 연동의 유지관리 부담을 감수하는 것이 합리적이라고 실측으로 보여지는 경우. (a)~(c) 중 (a)조차 아직 확인되지 않았다.

## 7. 대표 결정이 필요한 것 (1건)

**대화·문서 검색을 제품 기능으로 올릴 것인가.** 올리면 §8-가의 좁은 이슈(기존 D1 안의 어휘 인덱스 + 결과 상한·창 정책·LIKE 50바이트 적합화)가 필요하고, 올리지 않으면 #2002는 "신규 Vector DB 불필요" 결론으로 종결할 수 있다. 신규 자원(Vectorize·외부 서비스)·데이터 처리 정책 변경은 이 결정과 무관하게 계속 보류가 맞다(#2002 처리 원칙, Owner D4).

## 8. 후속 이슈 제안 (#2002 §조사 4의 "별도 생성" 대응 — 이 문서에서는 만들지 않는다)

- 가. `[UTIL][SEARCH] D1 FTS5 어휘 인덱스로 대화·문서 본문 검색 올리기` — 범위: 마이그레이션 1개(허상 테이블 + 트리거 또는 재색인 배치), `search_conversations` 랭킹 전환, 결과 상한·창 정책의 사용자 가시화, 한국어 토크나이저 품질 검증. 신규 자원 없음.
- 나. `[CHAT][SECURITY] product_scope 누락 3경로 맞춤` — §3-나. 보안 결함 단정 아니라 경계 일관성 맞춤.
- 다. `[CLAW][MEMORY] 승인 기억을 프롬프트에 주입할지 결정과 배선` — §1-2 #10. 제품 결정 선행.
- 라. `[CHAT][SEARCH] LIKE 패턴 50바이트 한도 적합화` — §3-가. `substr()` 우회 전례(`history.py:2131`) 재사용 또는 질의 바이트 상한 도입. 운영 입증 1회와 함께.

## 9. 완료 기준 대응 (#2002)

| 완료 기준 | 상태 |
|---|---|
| 최신 Core/제품 저장·검색 inventory와 증거 | 충족(§1, 파일:라인) |
| 제품 기능별 누락/재사용 경계 | 충족(§2, §8) |
| 신규 Vector DB 필요/불필요 근거 결론 | 충족 — 불필요(§6) |
| 필요시 옵션별 비용·데이터 경계·실행 이슈 | 조건부 정리(§5). 비용 단가는 공식 미확인으로 남김 |
| #5151/#2409와 상충 없는 단일 책임 경계 | §10 |

## 10. #5151·#2409와의 경계

- #5151 C안(짧은 동기 실행은 제품 + 공통 Core, Engine은 지속 실행으로 축소)과 상충하지 않는다. §8-가의 어휘 검색은 제품 Worker 안에서 D1 SQL로 끝나는 짧은 동기 조회이므로 Engine 경유가 필요 없고, Engine `memory_rag` 활성화를 요구하지 않는다.
- #2409의 책임 분류를 유지한다. 검색·기억 **저장 스키마는 제품 소유**, **권한·랭킹 의미는 공통 Core 계약**(`PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md:53,64,136`, `PADIEM_AI_RETRIEVAL_CONSUMER_CONFORMANCE_v1.md`)이며, 이 문서는 그 경계를 옮기지 않았다. Wave 1+ 소스 이동은 #2409가 여전히 미승인이므로 제안하지 않는다.
- 과거 E9 A4 절차(#1967/#1753)는 재개 대상으로 적지 않았다. 2026-10-25 정합화대로 역사 문구로만 다뤘다.

## 11. 이 조사의 한계 (추정과 미확인 구분)

- §4 수치는 전부 **로컬 합성**이다. 운영 D1·운영 데이터·운영 네트워크를 한 번도 호출하지 않았다. 운영 지연·운영 재현율 대리값으로 쓰지 말 것.
- 운영에서 대화 검색이 실제로 얼마나 쓰이는지(실사용 여부)에 대한 증거는 저장소에 없다. §1의 "실사용 검증" 열이 대부분 약한 이유다.
- Vectorize·외부 서비스의 **가격과 지연 수치는 확인하지 않았다**(확인한 공식 페이지에 없음). 추정치를 적지 않았다.
- D1 FTS5 지원은 공식 문서 인용이며, **이 저장소의 Python Worker 경로(workerd SQLite)에서 실제 동작하는지는 미검증**이다. §8-가 착수 시 첫 확인 항목으로 붙여야 한다.
- 한국어 형태소 기반 품질은 측정하지 않았다(§4-다의 FTS5 실험은 기본 토크나이저).
- 이 문서는 #2002가 요구한 판단 자료이며, 구현·배포·자원 생성을 승인하지 않는다.
