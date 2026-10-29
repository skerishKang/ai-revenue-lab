# 저장소 잔재 분류표 (2026-10-29)

```text
DOC_ROLE=REPO_LEFTOVER_CLASSIFICATION
STATUS=조사·검증 완료(서버·패키지·화면) / A 18·B 12건은 주제별 PR로 제거 중 / C 12건은 대표 결정 완료(2026-10-29, §5)
       — 제거 2(C1·C3)·교정 5(C2·C8·C10·C11·C12)·유지 3(C4·C5·C7)·부분 또는 조건부 2(C6·C9)
ISSUE=대표 요청(잔재 제거), 발단: chat mode 잔재
RELATED=apps/padiem-chat/app/request_contract.py, apps/padiem-chat/app/chat_modes.py(PR #6234로 삭제),
        docs/operations/TEST_TIME_ANCHOR_AUDIT_20261029.md
경계: 이 문서는 분류와 근거만 남긴다. D1 표·열 제거는 제안하지 않는다(필요하면 C로 올린다).
```

## 1. 무엇을 찾았나 / 방법

대표가 만들지도 결정하지도 않은 잔재를 찾는다. 두 관점으로 저장소 전체를 스캔했다
(`apps/padiem-chat` 우선 → 나머지 `apps/`·`packages/`).

1. **도달 불가능**: 어디서도 쓰이지 않거나, 서버가 막아서 도달할 수 없는
   옵션·모드·플래그·라우트·카탈로그·설정값.
2. **결정 위반**: 자동 모델 선택, 조용한 대체(fallback)/재시도로 다른 모델 사용,
   임의 상한(플랫폼 물리 한계 제외), "곧 지원/준비 중" 빈 약속, 가짜 성공 표시, 숨겨진 유료 전환,
   화면에 있는데 동작이 연결되지 않은 버튼·메뉴, 항상 같은 값의 죽은 플래그와 그 분기.

각 항목은 (a) 식별자와 문자열 값으로 저장소 전체 grep, (b) 생산 코드 호출처 수, (c) 그 값을
고정하는 테스트 어디인지로 검증했고, 서브에이전트 결론과 **이 문서 자신의 인용까지 직접 바로잡았다**
(§6).

판정: **A** 확실히 죽음 → 제거 / **B** 대표 결정 위반 → 제거 / **C** 애매 → 대표 확인(지우지 않는다).

## 2. 발단 항목 — chat `mode` (제거 완료: PR #6234)

| 항목 | 위치 | 근거 | 분류 | 제거 시 영향 |
|---|---|---|---|---|
| 4지 카탈로그(자동/빠르게/균형/깊게) + `mode` 요청 키 + 송신자 | `app/chat_modes.py`(삭제), `app/request_contract.py:167`(삭제), `static/app.js:3302`, `static/util-menu.js:62`(mode 한 줄), `apps/padiem-council-apps/static/council-app.js:80`, 캐너리 3 | 서버가 `auto`만 허용 → 3개는 도달 불가, `auto`는 #4844로 폐지된 자동 선택의 빈 표시; 모듈 import 생산 코드 0건; UI는 이미 등급 셀렉터로 대체되어 `test_b62_1815_mode_presentation.py`가 구 문구의 부재를 고정 중 | A+B | 키는 조용한 무시가 아니라 미지 항목으로 거절한다. 거절 코드는 **422**다(`BrowserRequestError` → `chat_routes.py:346-348`과 `:879-881`이 `invalid_request`로 낸다. 400이 아니다 — §6). 배포 전 열려 있던 구 탭은 한 번 422 후 새로고침 |

## 3. A — 확실히 죽은 것 (주제별 PR로 제거)

| # | 항목 | 위치 | 근거(호출처 0 등) | 제거 시 영향 | 오늘 고정하는 테스트 |
|---|---|---|---|---|---|
| A1 | 스킬 alias 계층 `Skill/ SKILL_REGISTRY / get_skill / skill_public_metadata` | `app/skills.py` 전문 | `from app.skills import`가 **테스트 6개**(`test_skill_contract`·`test_skills`·`test_grounding`·`test_runtime`·`test_projects`·`test_private_auto_stream_client`)뿐이고 생산 코드 0건. 실제 리더는 전부 `task_modes` 직접 import(b14_client, tier_identity_client, auto_grounding, request_contract, grounding, b66_search_boundary) | 중복 공개 표면 소멸, `task_modes`가 단일 출처 | `test_skill_contract.py`·`test_skills.py` |
| A2 | `KILO_B14_MODEL_ID` ("compatibility alias for the Kilo free test lane") | `app/model_policy.py:218` | 정의 외 참조 = `tests/test_model_policy.py:17` 한 곳 | Kilo 브랜드 문자열 제거 | `test_model_policy.py` |
| A3 | `UNASSIGNED_B14_MODEL_ID = "padiem-profile/medium-unassigned"` ("retained for older adapters") | `app/model_policy.py:222`(+빈 능력 행 :277) | adapter import 0건; 자기 행과 `test_model_policy.py:29,148,159`만 | 카탈로그 유령 모델 id 소멸 | `test_model_policy.py` |
| A4 | 이미 제거된 상한을 "호환" 이름으로만 남긴 심볼 | `app/request_contract.py:30-32`(`MAX_MESSAGES`·`MAX_MESSAGE_CHARS`·`MAX_TOTAL_MESSAGE_CHARS = None`) + `app/main.py:64-66` import | 어느 코드도 읽지 않음; `test_browser_conversation_state_contract.py:23-24`는 JS에 문자열이 **없음**을 검사 | #4379 선례(키우지 말고 없앤다)대로 이름까지 제거 | 없음 |
| A5 | `MAX_MESSAGE_CHARS=2_000`/`MAX_REPLY_CHARS=2_000` "no longer enforced" | `app/b66_ai_conversation.py:57-58` (+`__all__:927-928`) | docstring이 스스로 미집행이라 선언; 호출처 0 | 죽은 문자 상한 제거 | 없음 |
| A6 | 두 갈래가 같은 값을 반환하는 3항 연산 | `packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py:107-112`(사용 :261) | 저장소 전체 grep: 정의·사용 각 1회뿐 | "전환되지 않는 전환" 소멸; `MUSE_ROUTE_STATUS`는 유지 | 없음 |
| A7 | `OWNER_PINNED_TIER_FALLBACK_ON_RECOVERABLE_ERROR = True` | `product_tier_routes.py:90` | 식별자 grep → 정의 줄뿐. "대체 허용"을 주장하지만 읽는 데가 없음 | 대체 허용 주장 문구 소멸 | 없음 |
| A8 | `= None`이 된 5개 상한과 그로 인해 도달 불가한 분기 | `packages/padiem-ai-core/padiem_ai_core/execution_runtime.py:48-55,229-230` + `__init__.py:86-88,613-615` 소비처 `apps/padiem-ai-engine/app/web_research_service.py:222-228,485,493,501` | 값이 정의상 `None`이라 `is not None` 분기가 영구 거짓; `MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS`만 Chat 쪽에서 실사용(별개) | 영구 거짓 분기 소멸 | `test_engine_dispatch_preinstruction_4468.py:117-122`(monkeypatch로 되살림 → 제거 시 함께 정리) |
| A9 | 고아 모듈 5개 | `padiem_ai_core/{adapter_conformance,agent_delegation,b14_output_limits,template_cloner_analyzer,template_cloner_skill}.py` | 식별자 grep → 서로와 자기 테스트, `__init__` 재수출뿐; `template_cloner_analyzer.py:13` "Phase A ships no live route"; `b14_output_limits`는 `PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING=None`이 먹이는 공급기 | 안 만들어진 "Phase A" 약속과 미사용 위임 상한(4/8) 소멸 | `test_b14_output_limits.py:151`(소스 라인 문자열 고정 → 부존재 검사로 교체) |
| A10 | 고아 모듈 2개(패키지 재수출 포함) | `padiem_control_plane/{b14_routing_policy.py,model_assignment_sqlite_reference.py}` | `TrustedB14RoutingPolicyV1` 등 → `__init__.py` 재수출뿐; `SQLiteModelPolicyStore`는 테스트 전용. 자기 docstring이 "never a second production authority" | 모델 지정 제2출처(사용 안 함) 제거 | `test_4453_model_assignment_policy.py` |
| A11 | 은퇴한 scorer용 능력 라우팅 어댑터 | `apps/korean-ai-platform/app/pilot/capability_routing.py:1-60` | `capability_routing` grep → 자기 테스트 1건 | 없음 | `test_capability_routing.py` |
| A12 | 비-CAS(행 수 미검증) 호환 쓰기 경로 | `apps/living-fiction/app/branch_generation_request_repository.py:431,434,447,460` | 각 식별자 정의 1회, 호출 0건; CAS 버전이 :200/:390/:413에서 실제 사용 | rowcount를 보지 않는 갱신 경로 소멸 | 없음 |
| A13 | "호환 표면" 재수출 블록 2곳 | `apps/padiem-ai-engine/app/orchestration_service.py:91-110`, `agent_skill_service.py:619-637` | `_MAX_*` 심볼 → import 줄과 `orchestration_wire` 정의·테스트뿐 | `orchestration_wire`가 단일 표면 | `test_orchestration_wire.py:38-45,95`(재수출 목록 고정 → 부존재로 교체) |
| A14 | 자체 문서로 "not wired"를 인정한 티어 레지스트리 | `apps/korean-ai-platform/app/pilot/tier_registry_v1.py` 전문 | import는 자기 테스트 하나; `product_tier_routes.py:27`은 문서상 참조. 대체자 = `product_tier_routes` | 두 번째 티어 출처 소멸 | `test_tier_registry_v1.py`, `.github/tests/test_b67_space_bunny_primary_parity.py:114-151`(문자열 고정 → 교체), `test_tier_route_consumer_coverage.py` |
| A15 | 단계적 티어 그룹 플래너(쓰지 않는 상한 포함) | `packages/padiem-control-plane/padiem_control_plane/tier_model_groups.py:1-230`(`MAX_GROUP_MODELS=32`:25, `MAX_BACKUPS=1`:26, `suggest_explicit_fallback`:208) | 공개 심볼 9개 모두 모듈+자기 테스트 외 0건 | 사용 안 하는 모델 명부 제2출처와 대체 제안 함수 소멸 | `test_tier_model_groups.py` |

## 4. B — 대표 결정 위반 (동일하게 제거 대상)

| # | 항목 | 위치 | 근거 | 제거 시 영향 | 고정 테스트 |
|---|---|---|---|---|---|
| B1 | 자동 선택의 마지막 이름 `AUTO_B14_MODEL_ID = "b14/auto"` | `app/model_policy.py:60,276` | 실제 사용처는 전부 **문자열 거부 가드**(b14_client.py:640,927,1009; b66_registered_model_boundary.py:31; b66_*_routes) — #4844로 자동 선택 폐지 | 자동 id가 제품 카탈로그에서 사라짐 | `test_5002_model_path_classification.py:107-108` |
| B2 | 사용자 입력 텍스트에서 `/plus·/pro·/max·/kilo`를 뽑아 등급을 바꾸는 슬래시 셀렉터 | `app/model_policy.py:255-261,494-516`(+`_strip_hidden_tier_alias`) | 브라우저는 등급을 별도 필드로 보낸다(`static/app.js:3302`); `request_contract.py:262-266`이 스스로 "compatibility/test surface"라 적음. 사용자가 `/max`를 치면 등급이 바뀜 | 숨겨진 전환 종료(등급은 명시 선택만 유효) | `test_model_policy.py:111,141`, `test_product_tier_identity.py:182` |
| B3 | `country` 요청 항목 — 검증만 하고 아무도 읽지 않음 | `app/request_contract.py:134-138,154-157` | `declared_country` 호출처 0건(정의 파일뿐), `COUNTRIES`를 읽는 `project_file_routes.py`는 자체 파싱을 재구현. 그런데 `council-app.js:79-83`은 계속 `country`를 보냄 → 화면에서 고른 국가가 채팅 경로에서 조용히 버려짐 | 보내는 쪽·받는 쪽을 함께 제거(또는 실제 기능으로 연결 — 대표 확인 시 C로 강등 가능) | `test_6046_country_contract.py` |
| B4 | 스코어러 시대 공개 필드 4개: `task_type`·`optimize_for`·`provider_order`·`allow_paid`(`max_attempts`는 파싱 후 폐기) | `apps/korean-ai-platform/app/pilot/gateway.py:186-188,368-420`, `routing_policy.py:58-64` | 검증 후 `ignored_options`로 기록만 됨; 라우팅 소비처 0건(`required_capabilities`만 실소비 → 유지) | 아무 일도 하지 않는 공개 API 노브 제거 | `test_alpha1.py:1436-1462`, `test_routing_policy.py:147-153`, `test_b62_free_routes.py:115` |
| B5 | `allow_external_fallback` 기본값 True(실제 강제 지점 없음) | `gateway.py:655,888`, `auto_stream_gateway.py:343`, `platform_secrets.py:175` | 20개 참조가 전부 기본값/pass-through, 검증 지점 없음 | "다른 모델로 대체 허용" 신호 제거 | `test_alpha1.py` 다중 후보 케이스 |
| B6 | 자체 선언 32 KiB 상태 상한(형제 모듈은 1 MiB) | `app/b66_ai_conversation.py:60` → `b66_ai_conversation_store.py:81,118` | 플랫폼 한계가 아닌 자체 상한; 같은 개념의 `b66_guided_draft.py:20`은 `1024*1024` → 임의·비일관(#4379가 제거한 계열) | 긴 인용 대화가 거부되는 현상 종료 | `test_b66_ai_conversation_routes_4412.py` |
| B7 | `b14/auto` 레인 전체(자동 선택 + 2모델 고정 폴백 체인) | `apps/korean-ai-platform/app/pilot/{routing_policy.py:50-168,auto_stream_gateway.py,auto_availability.py:15-23}`, `router_core.py:49`(`AUTO_FALLBACK`) | 진입 조건 `ensure_generic_auto_enabled`는 `B14_ENABLE_FUTURE_AUTO`가 없으면 422 "reserved for future development"; 그 env는 **어디서도 설정되지 않음**(`b14.env.example:56`은 빈칸, 나머지는 전부 monkeypatch) | 빈 약속과 `agnes-3.0-flash → poolside/laguna-s-2.1` 암묵 대체 명부 소멸 | `test_deferred_auto_20261016.py`, `test_routing_policy.py`, `test_auto_stream_gateway.py` |
| B8 | 원시 provider id로 된 능력 카탈로그 행 3개 | `app/model_policy.py:273-275` | `model_supports()`는 항상 티어 해석 뒤 모델에 `"image"`로만 호출(b14_client.py:835, chat_routes.py:887); 저 티어 3단은 한 라우트로 수렴 → 행 도달 불가. provider 이름이 제품 카탈로그에 노출(브라우저 QA 금지어 목록과 충돌) | 선택 불가능한 카탈로그 행 제거 | `test_model_policy.py:83,167`, `test_plus_space_bunny_image.py` |

## 5. C — 대표 결정 완료(2026-10-29)

대표가 열 번을 물어온 항목에 답했다. 결정만 실행하고, 결정과 다른 전제로 적혀 있던 근거는 §6에서
직접 바로잡았다(특히 C8·C9·C11과 거절 코드 번호).

| # | 항목 | 위치 | 대표 결정 | 실행 PR |
|---|---|---|---|---|
| C1 | 작업 모드 8종 중 6종(explain/write/translate/summarize/code/brainstorm)이 화면에서 선택 불가 | `app/task_modes.py:54-116`, `static/index.html:833,839`(`data-skill="plan"`, `"auto"`) | **제거**. `auto`·`plan`만 남기고 6종은 명부에서 뺀다. 서버는 6종을 **미지 값으로 거절**한다(조용히 `auto`로 대체하지 않음). 상태 코드는 이 코드의 규범인 422 `invalid_request`(§2·§6) | PR-K |
| C2 | AI 등급 알약의 라벨이 `mode` 키에 묶여 "기본 대화"(EN "Standard chat")로 나가던 것 | `static/locale.js:44,304` ← 소비처 두 개: `:669` 텍스트 바인딩 `.model-pill span:last-child`, `:731` aria 바인딩 `.model-pill`. `static/index.html:1163`, React 복제본 `apps/padiem-chat-react/src/components/Composer.tsx:209` | **교정**. 스크린리더 라벨은 "AI 등급" / "AI tier"로 맞춘다. `mode`라는 이름의 잔재 키는 없앤다. 텍스트 바인딩은 알약이 보여주는 등급 이름 자리인데 런타임 소유자(`product-capabilities.js:1731,1733`)가 이미 그 span과 aria를 다시 쓰므로, 바인딩을 떼고 마크업·런타임에 맡긴다 | PR-L |
| C3 | "대화 검색 준비 중" | `static/locale.js:46,306`; 소비 `static/index.html:101`, `static/conversation-search.js:107` | **제거**. 검색 버튼에는 이미 진짜 disabled 상태가 있다(`conversation-search.js:118-120`), 약속 문구만 내린다 | PR-L |
| C4 | `PRODUCTION_HARK_OFFICE_CHOOSER_ENABLED = False` 상시 게이트 | `app/claw_office_chooser_routes.py:189` | **유지**(Hark 제품 작업 #3936 소관). 이 레인은 손대지 않는다 | — |
| C5 | 커넥터 레인의 문서화 HOLD 플래그 13종 | `apps/padiem-chat/app/connector_*` | **유지**(해당 레인 판단). 제거 제안 철회 | — |
| C6 | 재시도·길이 예산 10/4/256 | `apps/padiem-ai-engine/app/orchestration_wire.py:39-41` | **부분 제거**: 길이 예산 256(`_MAX_CANCEL_REASON_LEN`)은 없앤다. 재시도 10/4는 네트워크 대기 상한으로 유지하고, 근거(커넥터 안정성 기준: 네트워크 대기에는 상한을 허용한다)를 주석으로 남긴다 | PR-D |
| C7 | 테스트 전용 라우트 2건(`/api/b66/quote/native-sol-scope`, `/api/connectors/github/repositories`) | `app/*routes.py` | **유지**. 서버-서버·관리 표면은 클라이언트 무참조가 정상 | — |
| C8 | "GitHub 직접 연결은 준비 중입니다" vs 실제 라우트 존재 | `static/locale.js:136,396` | **교정 = 삭제**. 실사로 이 키의 소비처는 **0건**이었고(§6), 라우트는 마운트돼 동작한다(`app_factory.py:602-604`). 죽은 거짓 약속 키를 ko·en에서 내린다 | PR-L |
| C9 | `app/main.py`의 "legacy imports" 재수출 블록 | `app/main.py:20-79`(파일 전체가 재수출) | **조건부 제거**: 심볼별로 소비처를 확인해 미사용만 없앤다. main.py가 import하는 이름은 **76개**이고, 외부(`from app.main import`·`app.main.<name>`) 참조가 있는 것은 `create_app`·`api_chat_stream` **둘뿐**이다. `app`은 이 파일이 정의한다. 나머지 74개를 내린다 | PR-B |
| C10 | Drive OFF 토글의 문구 | `static/claw-connection-chips.js:233-234` | **교정(동작 불변)**: "Google 권한은 잠시 멈출 수 없어요. 완전히 끊으려면 Google 계정 > 보안 > 타사 앱에서 해제하세요" + 링크. 이 파일에는 `href`가 아직 없으므로 앵커를 새로 붙인다 | PR-L |
| C11 | PDF 변환 안내의 범위 혼동 | `static/claw-web-xlsx-sources.js:274` vs `:245-248` | **교정**: 별도 승인이 필요한 것은 **수정된 XLSX의 PDF 변환**이고, `:247`의 "승인된 표준 견적 PDF 미리보기"는 이미 동작하는 별개 기능이다. `:274`를 "변환"만 가리키도록 고치고 미리보기 문구는 건드리지 않는다 | PR-L |
| C12 | 영어 표에 한국어 라벨 | `static/product-capabilities.js:90`(`admin: ["Padiem 관리자", ""]`) | **교정**: 영어 행만 `"Padiem Admin"`으로. 한국어 행(`:75`)과 서버명(`b66_grade_models.py:38` `B66_ADMIN_NAME`)은 그대로 둔다 — 서버가 한국어 명을 그대로 주는 사실은 PR-L 본문에 남긴다 | PR-J |

## 6. 검증에서 바로잡은 것 (서브오디트 결론 → 실제)

- "스킬 6종이 도달 불가라 A" → 서버는 그 값들을 **허용**한다. 화면이 만드는 값은
  `plan`/`auto`가 전부이지만 직송 요청은 통과하므로 **C1**으로 강등했다(삭제 전 대표 확인).
- "`app/main.py` 재수출은 죽었으니 A" → `from app.main import`가 82건. 재수출 표면은 살아있고
  특정 심볼만 미사용 의심 → **C9**.
- "browser가 `country`를 보내지 않는다(grep 0)"는 것은 **틀렸다**:
  `apps/padiem-council-apps/static/council-app.js:79-83`이 보낸다. 그래서 B3의 근거를
  "검증만 하고 읽지 않음 + 보내는 쪽은 council"로 다시 썼다.
- 화면 오디트의 "죽은 locale 키 30종" 목록에는 오탐이 섞여 있다: `claw-actions-aria`는
  `locale.js:735`의 aria-label 테이블이 `.claw-chips`에 붙인다(살아있음). 그래서 A17은
  **키별 재확인 조건부**로만 제거한다(§7의 별표).
- "PDF 변환 notices가 실라우트와 모순(B)" → 그 문구는 **수정된 XLSX의** PDF 변환을 두고 한 말이고,
  같은 파일에 이미 "승인된 표준 견적 PDF 미리보기"(`claw-web-xlsx-sources.js:245-248`)가 존재한다.
  즉 모순이 아니라 범위 문제 → **C11**.
- "Drive OFF 토글이 toast-only no-op이라 B" → 코드에 이유가 적혀 있다: Google 권한에는 되돌릴 수 있는
  일시 중지가 없어 조용히 삭제를 하지 않는 것(`claw-connection-chips.js:230-237`). 고장이나 빈 약속이 아니라 **어포던스/문구 결정** → **C10**.

대표 결정을 실행하기 전에 위치와 코드를 한 번 더 확인하면서, 이 문서가 틀린 곳도 고쳤다:

- **§2와 C1의 거절 코드**: 400이 아니라 **422**다. `BrowserRequestError`를 `chat_routes.py:346-348`과
  `:879-881`이 `invalid_request` 422로 변환한다. 같은 계열을 400으로 바꾸면 다른 모든 요청 거절의
  가격을 함께 바꾸므로, 이 코드의 규범(422)을 그대로 두고 문서를 정정한다.
- **C8의 인용이 틀렸다**: 소비처로 적어둔 `static/app.js:5935`(GitHub 연결 성공 처리)과
  `static/claw-connection-chips.js:65`(`/api/connectors/github/status` 조회)은 그 locale 키를 읽지
  않는다. 저장소 전체 grep에서 `claw-home-github-setup`은 ko/en 정의 두 줄뿐 — **소비처 0건**.
  라우트는 마운트돼 동작하므로(`app_factory.py:602-604`) 결정은 "문구 수정"이 아니라 "죽은 키 삭제"다.
- **C6의 256은 잘라내는 예산이 아니라 거부하는 상한이다**: `_parse_cancel_reason`
  (`orchestration_wire.py:206-209`)은 256자를 넘으면 `ServiceContractError`를 낸다. 같은 조건의
  `1 <=` 하한은 바로 앞 `.strip()`이 막으므로 도달 불가능하다. 제거의 실제 효과는 "256자 초과 취소
  사유를 거부하던 상한의 폐지"이고, 아무 것도 잘리지 않는다.
- **C9의 "13종"은 틀린 수**: 재수출 블록은 첫 인용(57-79행의 32개)만이 아니라 파일 앞쪽 import까지
  포함해 **76개 이름**이다. 저장소 전체에서 `from app.main import <name>`·`app.main.<name>`을
  이름별로 세면 참조가 있는 것은 `create_app`(약 80개 테스트 + `app/worker.py:116`)과
  `api_chat_stream`(테스트 2건) 둘뿐이고 나머지 **74개는 0건**이다. `app`은 main.py가 정의한다.
- **C11의 인용문은 저장소에 없다**: "수정된 XLSX의 PDF 변환"이라는 문자열은 어디에도 없다. 실제
  문장은 `claw-web-xlsx-sources.js:274`·`:803`·`:1142`이고, `:245-248`의 미리보기는 다른 기능이다.
  세 문장은 locale 키가 아니라 하드코딩 한국어 문자열이라 en 표가 아직 없다.
- **C10도 locale 키가 아니다**: `claw-connection-chips.js:233-234`의 인라인 `message(ko, en)` 리터럴이고,
  이 파일에는 `href`가 한 번도 나오지 않는다. 링크를 넣으려면 앵커가 새로 필요하다.

## 7. 화면(`apps/padiem-chat/static`) — 버튼·메뉴·카피

| # | 항목 | 위치 | 근거(호출처 0 등) | 분류 | 제거 시 영향 | 오늘 고정하는 테스트 |
|---|---|---|---|---|---|---|
| U1 | 스킬 패널 통째로 죽은 DOM | `static/index.html:129`(`#skillsNavButton` markup에서 영구 `disabled`), `:368-381`(`#skillsDialog`, `#skillsDialogClose`), `locale.js:217,240` | `skillsDialog`를 읽는 JS는 `locale.js:735`의 aria 지정 한 줄뿐이고 `showModal()`/`.show()` 호출·클릭 핸들러가 없다 | B |내비게이션 행·다이얼로그와 키 6종(`nav-skills`·`skills-kicker`·`skills-title`·`skills-note`·`skill-custom`·`skills-grid-aria`) 소멸 | 없음(`test_connectors_bright_calendar_state_ui.py:224`는 CSS **부재**만 검사) |
| U2 | "준비 중인 기능 5개" disclosure — 5개 버튼 모두 id·data·핸들러 없음, 그중 두 줄은 **거짓** | `index.html:1049-1072`, `locale.js:181` | Markdown/DOCX 다운로드는 실제로 존재(`app.js:6126` `clawResultDocx`, `claw-quote-compare.js:312,329`) | B | disclose 블록 + locale 키 10종. 거짓 안내 제거는 사용자 정확도 개선 | `test_b62_2532_claw_chat_continuity.py:240,244` |
| U3 | "지원 형식은 추후 안내합니다" — 형식 목록은 클라이언트에 이미 있음 | `index.html:838`, `locale.js:234` vs `attachment-capabilities.js:60-88`(`imageFormats`/`documentFormats`) | `app.js:3603-3612`는 `hidden`만 토글하고 패널에 형식을 채우는 코드가 없다 | B | 빈 약속을 기존 목록 표시로 교체(또는 패널 제거) | 없음 |
| U4 | Discord·Kakao Business 상시 "준비 중" 카드 | `index.html:343-344`, `app/connector_status_projection.py:136-163` | 카드에 `data-connector-id`·연결 어포던스가 없고 서버 투영에 두 항목이 없어 켜질 수 없다 | B | 카드 2개 + `connectors-support-deferred` 제거 | `test_b54_connectors_surface_truthful.py:46,169,342,386` |
| U5 | 죽은 `window.Padiem*` 공개 객체 3종 | `claw-mesh-capture.js:133`, `claw-office-chooser.js:260`, `conversation-search.js:284` | 세 심볼의 참조는 정의 줄 3건뿐(저장소 전체 grep) | A | export 블록만 제거, 동작 불변 | 없음 |
| U6 | `TIER_COPY` 각 항의 두 번째 요소 `""`(읽는 데 없음) | `product-capabilities.js:71-75,86-90`; 소비 `:554` + `[0]`만 쓰는 지점들 | `[1]` 접근이 저장소에 없음 | A | 문자열 평탄화. 유료 고지 자체는 실재(`copy.upgrade`/`copy.truth`) → 숨은 유료 전환 아님 | 없음 |
| U7* | 소비자 없는 locale 키 약 30종 | `locale.js:25,43,52,150,234,255,266,267,288` | 키 문자열·동적 접두 build 모두 grep; 단 **오탐 1건 확인**(`claw-actions-aria`는 살아있음, §6) | A* | ko/en 쌍 정리, 렌더 변화 없음 | 없음 |
| U8 | 영어 블록에 한국어 라벨 `en.admin: ["Padiem 관리자", ""]` | `product-capabilities.js:90` | 같은 표의 `:75`와 불일치 | C12 → 교정 결정 | 영어 행만 `"Padiem Admin"`으로. 한국어 행과 서버명(`b66_grade_models.py:38`)은 그대로다 | `test_admin_model_select_261018.py:208`(한국어 행을 유지하면 통과) |

별표(*)는 제거 PR에서 항목별로 다시 확인하라는 표식이다.

## 8. 제거 계획 (주제별 작은 PR)

§5의 대표 결정은 같은 표를 손대는 PR에 합쳤다(이중 배정 방지: A12는 PR-G에서만 다룬다).

1. ✅ **PR #6234** — chat `mode` 잔재(§2).
2. **PR-B** Chat 서버 죽음 심볼·alias — A1,A2,A3,A4,A5 + B1 (`skills.py`, 모델 id 3종, `= None` 상한
   이름들) + **C9**(`app/main.py` 재수출 32종 중 미사용을 확인한 것만 내리고 `create_app`·
   `api_chat_stream`·`app`·`STATIC_DIR`은 남긴다).
3. **PR-C** `country` 키 양쪽 제거(B3) — contract·`council-app.js`·`test_6046_*`.
4. **PR-D** packages·engine 고아 모듈과 재수출(A6,A7,A8,A9,A10,A13,A15) + **C6**
   (`_MAX_CANCEL_REASON_LEN` 256 폐지, 재시도 10/4는 근거 주석과 함께 유지) — 문자열 고정 테스트는
   부존재 검사로 교체.
5. **PR-E** 숨은 전환·대체 신호(B2,B5,B8) — 등급 슬래시 셀렉터, 대체 허용 기본값, provider 노출 행.
6. **PR-F** 플랫폼 pilot 레인(B4,B7) — 소유 레인 통보 후(테스트 다수 얽힘). 확인이 필요하면 멈추고 보고한다.
7. **PR-G** `tier_registry_v1`(A14) + living-fiction 비CAS(A12) — 별도.
8. **PR-H** 화면 죽은 표면 — U1(스킬 패널) + U2(거짓 안내 5종 disclosure) → markup·locale 키·
   `test_b62_2532_*:240,244`와 `test_connectors_bright_calendar_state_ui.py:224`를
   "그 블록이 존재하지 않는다" 검사로 교체.
9. **PR-I** 화면 빈 약속 — U3(형식 목록) + U4(Discord/Kakao 카드).
10. **PR-J** 죽은 export·locale 정리(U5,U6,U7*) + **C12** — U6과 C12가 같은 표(`TIER_COPY`)를
    고치므로 한 PR에서. U7은 키별로 소비처를 다시 확인한 것만 제거한다.
11. **PR-K** 작업 모드 6종 제거(**C1**) — `app/task_modes.py` 명부를 `auto`·`plan` 둘로 줄인다.
    6종은 명부에서 사라지는 순간 `request_contract.py:173-179` 경로가 422 `invalid_request`로
    거절하게 되므로(조용한 `auto` 대체 없음), `test_skills.py`·`test_skill_contract.py`·
    `test_grounding.py`·`test_runtime.py`·`test_auto_grounding.py`의 "8종 존재" 단언을
    "2종뿐 + 6종은 거절" 단언으로 바꾸고 6종 거절 케이스를 추가한다.
12. **PR-L** 화면 문구·라벨 교정(**C2·C3·C8·C10·C11**) — `mode` 잔재 키를 ko/en 표에서 내리고
    알약의 aria 라벨을 "AI 등급"/"AI tier"로 교정(React 복제본 포함), "대화 검색 준비 중" 삭제,
    소비처가 0건인 GitHub "준비 중" 키 삭제, Drive OFF 문구를 사실대로(링크 추가),
    PDF 변환과 표준 견적 PDF 미리보기의 범위를 나누어 고친다.

모든 PR에서: 단언을 약화하지 않는다. "exists" 검사 → "no longer exists/거부된다" 검사로 바꾼다.
D1 표·열 제거는 제안하지 않고, 배포·D1 게이트 실행도 하지 않는다. C는 대표가 답한 뒤에 손대고, 답이
"유지"였던 C4·C5·C7은 코드·문서 그대로 남긴다.
