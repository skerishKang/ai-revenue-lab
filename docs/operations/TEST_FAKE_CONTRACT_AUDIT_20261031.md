# 테스트 가짜 객체 계약 감사 — 2026-10-31 (컴1 로컬2)

## 0. 결론

| 앱 | 가짜 클래스 수(파이썬) | 상 | 중 | 하 |
|---|---|---|---|---|
| padiem-chat | 148 | 9 | 52 | 87 |
| korean-ai-code-agent | 46 | 6 | 14 | 26 |
| padiem-file-lane | 0 (수제 스텁 8건) | 3 | 5 | 0 |
| **합계** | **194 (+file-lane 수제 스텁 8)** | **18** | **71** | **113** |

- **수정 2곳(가짜 11건 교체)**: kagent 읽기 포트 `read_bytes` 가짜 8건, chat Engine 스트림 트랜스포트 `stream_request` 가짜 3건 — 전부 `**kwargs`/`**call` 삼키기 또는 `timeout_seconds=None` 기본값(#6327 사고의 표면)을 실제 프로토콜 시그니처로 교체.
- **계약 테스트 2건 추가**(변형 검증으로 실패 능력 확인): `apps/korean-ai-code-agent/tests/test_fake_port_contract_261031.py`, `apps/padiem-chat/tests/test_fake_stream_transport_contract_261031.py` — 테스트 디렉토리 전체의 포트 메서드 정의를 ast로 수집해 실제 프로토콜과 대조. 어긋나는 가짜가 커밋되면 실패.
- 본 문서의 위험도 분류는 이름·문맥 유형 기준(§3). 상/중의 정밀 대조는 §2·§4, 수정은 §5.

## 1. 배경과 방법

이번 주 실제 사고 — 전부 "테스트 통과, 운영 첫 실행에서 실패":

1. **실행기 읽기(#6327 수리)**: 가짜 read 포트가 실제 포트의 `timeout_seconds` 검증을 거치지 않아 `timeout_seconds=None` 전달이 통과, 2026-10-29 이후 모든 PC 읽기 실패.
2. **큐**: 가짜 저장소가 실제 큐 스키마와 달라 운영 큐 메서드 실패.
3. **UI(#6319 수리)**: 하니스의 가짜 `insertBefore`가 자식이 아닌 기준 노드를 허용해 실제 브라우저 `NotFoundError`를 숨김.

교훈: 가짜는 실제 포트·설정 클래스의 시그니처와 검증을 공유해야 한다. 방법:

- 세 앱 테스트(`apps/*/tests/`)에서 `class (Fake|Stub|Dummy|Recording)*` 파이썬 정의를 전수 수집(파일:라인), 파일럿 브라우저 하니스의 JS 인라인 클래스(FakeSocket·FakeRecorder·FakeAudioContext·FakeNode 등)는 별도 §6.
- 위험도 '상' 후보(포트·저장·실행기·인증·파일 레인)만 소스와 정밀 대조.
- 사고와 직결된 2개 포트(read_bytes·stream_request)는 전수 대조 후 수정.

## 2. 정밀 대조 1 — kagent 읽기 포트 (`read_bytes`, 18건 전수)

실제 계약: `apps/korean-ai-code-agent/src/kagent/local_agent_meshcentral_private_reader.py:240` `MeshCentralFileReadPort` 프로토콜 — `read_bytes(*, node_ref, file_path, timeout_seconds: int, max_bytes=MAX_READ_ENVELOPE_BYTES)`. 실행기(`local_agent_oracle_mesh_executor.py:712`)는 `read_port.read_bytes(**call)`로 펼쳐 부르므로 **가짜 시그니처가 곧 계약**이다.

| 테스트 파일:행 | 가짜 | 수정 전 | 판정 |
|---|---|---|---|
| test_4139_oracle_mesh_executor.py:43 | _StubPort | `timeout_seconds=None` 기본 | **수정**(기본 60) |
| test_4139_oracle_mesh_executor.py:128 | _RecordingPort | `**call` | **수정**(센티널 기록 — "생략" 관찰 유지) |
| test_4139_oracle_mesh_executor.py:808 | _Recording | `**call` | **수정** |
| test_4139_oracle_mesh_executor.py:822 | _Refusing | `**call` | **수정** |
| test_4139_oracle_mesh_executor.py:846 | _Binary | `**call` | **수정** |
| test_4139_mesh_command_executor.py:402 | _ReadPort | `timeout_seconds=None` 기본 | **수정**(기본 60) |
| test_4139_pc_line_blockage_selfheal.py:677 | _ReadPort | `**call` | **수정** |
| test_5015_pc_read_port.py:132 | _ReadPort | `**kwargs` | **수정**(센티널 기록) |
| test_5573_mesh_presence_agent_name.py:32 | _StubPort | `**kwargs` | **수정** |
| test_4139_channel_refusal_leg.py:28 | 가짜 포트 | 필수 키워드 일치 | 통과 |
| test_4139_idle_poll_backoff.py:33 | 가짜 포트 | 필수 키워드 일치 | 통과 |
| test_4139_lighter_poll_beat.py:29 | 가짜 포트 | 필수 키워드 일치 | 통과 |
| test_4139_mesh_desktop_executor.py:36 | 가짜 포트 | 필수 키워드 일치 | 통과 |
| test_4139_mesh_output_fidelity.py:146 | 가짜 포트 | 필수 키워드 일치 | 통과 |
| test_4139_mesh_resend.py:30 | 가짜 포트 | 필수 키워드 일치 | 통과 |
| test_4139_mesh_read.py:104 | 가짜 포트 | 필수 키워드 일치 | 통과 |
| test_4139_meshcentral_private_reader.py:111 | 가짜 포트 | 필수 키워드 일치 | 통과 |
| test_4139_meshcentral_resident_lane.py:225 | 가짜 포트 | 필수 키워드 일치 | 통과 |

**관찰(운영 코드 변경 금지로 기록만)**: 프로토콜은 `timeout_seconds: int` 필수인데 실제 구현(`MeshCentralCliFileReadPort:395`)은 `timeout_seconds: int = 60` 기본 — 실행기가 생략할 수 있어야 한다는 #6327 주석과 맞추려면 프로토콜에도 기본값이 필요. 후속 운영 이슈 후보.

## 3. 위험도 분류 기준

- **상**: 실행·전송·저장·인증의 실제 운영 경로를 흉내내고, 그 가짜가 유일한 검증 통로인 것 — 포트(Transport/Port/Reader), 저장소(*Store), 실행기(Launcher/Process/Job/Interpreter), 인증·권한(Identity/Authority/Cipher/Broker/Gateway/Ingress/Https), 파일 읽기(DriveReader/OLE), 저널.
- **중**: 라우트 협력자(Resolver/Provider/Client/History/Dialogue/Documents/Publisher)와 pass-through 스파이 — 게이트는 운영 경로이나 실제 검증자를 함께 통과시키거나 오류 분기 한정이라 무음 드리프트 위험이 낮음.
- **하**: 표준 셸·DOM 흉내(Request/Response/Headers/Statement/DB/Query/Body/Reader/FormData/File/Socket/Recorder/Workers JS 객체) — 실제 검증은 프레임워크·실제 구현이 담당.

## 4. 정밀 대조 2 — chat Engine 스트림 트랜스포트 (`stream_request`, 전수 3건)

실제 계약: `apps/padiem-chat/app/worker_orchestration.py:162` — `stream_request(*, method, url, headers, body)` 필수 4키워드 + URL·method·body 검증(실제 구현 내 인라인).

| 테스트 파일:행 | 가짜 | 수정 전 | 판정 |
|---|---|---|---|
| test_3930_engine_ndjson_stream_port.py:104 | FakeTransport | `**kwargs` | **수정** |
| test_5484_canonical_subject_engine_admission.py:319 | _StreamTransport | `**kwargs` | **수정** |
| test_engine_orchestration_bridge_contract.py:676 | Transport | `**kwargs` | **수정** |

`FakeReader`·`FakeRequest`·`FakeBinding`(test_3930)은 Workers JS ReadableStream/fetch 흉내 — 파이썬 inspect 대조 불가, 유형 '중'으로 기록. 실제 구현의 잘못된 대상 거부는 기존 `test_worker_binding_stream_limit_and_wrong_target_fail_closed`가 담당(중복 추가 없음).

## 5. 추가된 계약 테스트와 검증

| 파일 | 대상 | 규칙 |
|---|---|---|
| `apps/korean-ai-code-agent/tests/test_fake_port_contract_261031.py` | tests 전체의 `read_bytes` 정의(ast 수집) | `**kwargs` 금지 / 실제 필수 키워드 누락 금지 / 실제에 없는 매개변수 금지 / `timeout_seconds` 기본 None 금지 / 실제 프로토콜 자체의 계약 고정 |
| `apps/padiem-chat/tests/test_fake_stream_transport_contract_261031.py` | tests 전체의 `stream_request` 정의 | `**kwargs` 금지 / kwonly 집합이 실제(method·url·headers·body)와 정확히 일치 / 기본값 금지 / 실제 프로토콜 계약 고정 |

변형 검증(mutation) — 계약 테스트가 실제로 실패하는 것을 임시 가짜로 확인 후 삭제:
- kagent: `**call` 가짜 → 실패 ✓, `timeout_seconds=None` 가짜 → 실패 ✓
- chat: `**kwargs` 가짜 → 실패 ✓

실행 결과:
- kagent: 계약 테스트 + 수정한 5개 파일 → **149 passed** (실패 1건은 baseline(main) 기존 실패 `QueueChannelOriginTests::test_a_queue_origin_that_could_leave_this_host_is_refused` — git stash 대조로 내 변경과 무관 확인)
- chat: 계약 테스트 + 수정한 3개 파일 → **97 passed, 0 failed**

## 6. 전수 목록 (유형 기준 분류)

### 6.1 padiem-file-lane (가짜 클래스 0 + 수제 스텁 8건 — 상 3 / 중 5)

| 가짜 | 위치 | 실제 대상 | 차이 | 위험도 |
|---|---|---|---|---|
| _FakeOle(+_Stream) | test_hwp_text.py:90-111 | `hwp_text._ole`(olefile 래퍼) | OLE 매직·FAT 검증 전부 생략, 2경로 하드코딩, payload 무시 — HWP 읽기 레인 전체가 이 가짜로만 검증 | **상** |
| parse_text 트립와이어 ×2 | test_parser_phase2.py:70,113 | `parsing.parse_text` | 시그니처 불일치(`*args`), 비호출 단언 — storage.py가 상단 import로 바뀌면 무음 우회 | **상** |
| 수제 ASGI receive/send ×2 | test_file_lane.py:152-170, test_parser_phase2.py:188-197 | uvicorn 서버 | H11 프레밍·실서버 scope 생략 — disconnect·disk_full·100MB 스트림 경로가 이 트랜스포트로만 검증 | **상** |
| ticket() 서명 헬퍼 ×3 | test_file_lane.py:26, test_5881:34, test_6338:38 | b14_service_proof + verify_ticket | base64 패딩 제거 방식이 실제 발급자와 다름, 3중복 — 실제 verify_ticket 통과 필수라 완화 | 중 |
| shutil.disk_usage 스텁 | test_file_lane.py:132,163 | storage.require_space | free만 있음, 507 분기 한정 | 중 |
| Upload.write 스파이 | test_file_lane.py:147 | storage.Upload.write | pass-through + 기록 — 실제 실행 보존 | 중 |
| Path.read_bytes 스파이 | test_parser_phase2.py:205 | parsing/storage의 read_bytes | pass-through 스파이, 단언 실패가 곧 테스트 실패 | 중 |

### 6.2 korean-ai-code-agent — 상 6 / 중 14 / 하 26 (46건)

**상 6**: `FakeMeshPort`(test_4139_meshcentral_private_reader.py:106)·`RecordingMeshPort`/`RecordingTextPort`(test_4139_meshcentral_resident_lane.py:216/187)·`RecordingTextPort`(test_4139_windows_verified_text_result.py:167) — PC 읽기·텍스트 포트(§2에서 시그니처 일치 확인, 계약 테스트가 이제 상시 감시) / `RecordingMaterialTransport`(test_local_agent_command_material.py:121) — 명령 재료 전송 / `FakeLauncher`·`FakeProcess`(test_3580_supervised_office_pair_producer.py:107/92) — 감독 실행 경로.

**중 14**: `FakePinnedHttps` ×2(TLS 고정 전송), `FakeAuthorizedGmailHttp`·`FakeAuthorizedHttp`·`FakeDriveReadHttp`·`FakeNetwork` ×4(Gmail/Drive/OAuth 전송 셸 — 실제 verify 통과 필수 아님), `FakeExcelRenderer`·`FakeExcel`, `RecordingEnviron`, `RecordingRevocationPort`, `RecordingPhysicalTransport`, `StubAdapter` ×3(문서·초안·검토 흐름).

**하 26**: `FakeViewPort`, `RecordingConnection`, `FakeBotApi`·`FakeHttpsConnection`·`FakeHttpResponse`·`FakeTrustedBinding`(텔레그램 셸), `FakeResponse`·`FakeConnection` ×2(문서 전송 셸), `FakeRuntime`, `FakePdfRenderer`, `FakeEngineTransport` ×2, `RecordingStdin` ×2, `_RecordingHost`, `Dummy(Exception)` 등 셸·관찰자.

(전수 파일·라인 목록은 저장소 히스토리 감사 커밋에 그대로 보존 — 각 테스트 파일 정의부. 유형 매핑은 §3.)

### 6.3 padiem-chat — 상 9 / 중 52 / 하 87 (148건)

**상 9**: `FakeTransport`/`FakeBinding`(test_3930 — §4 수정) / `RecordingSSETransport`·`RecordingBinding`(test_4483_final_dispatch_guard.py:123/90) / `RecordingTransport`(test_5015_chat_pc_engine_wire_fixture.py:54) / `FakeServiceTransport` ×4(test_service_binding*.py·test_b62_2544·test_4317) / `FakeProtectedStore`(test_4139_cross_stack_wss_device.py:168) / `FakeAuthenticatedCipher` ×3(byok·github_oauth_d1) / `FakeHistoryStore`·`RecordingHistoryStore`·`RecordingTaskAlertStore`·`FakeTaskAlertStore`(claw_automation·calendar) / `FakeDialogueStore`(test_4434) / `FakeGitHubStore`(토큰 저장). (저장·인증·전송 계열 — 개별 계약 테스트는 후속 후보.)

**중 52**: `FakeResolver`·`FakeTrustedResolver` ×5, `RecordingProvider` ×5, `FakeEngine`·`FakeEngineClient`·`FakeEngineBinding` ×4, `FakeDialogueClient` ×2, `FakeHistory` ×7, `FakeDocuments`·`FakeHeaders`·`FakeHeadersIterator` ×5, `FakeDriveReader`, `RecordingDelivery`·`RecordingInterpreter`·`RecordingUsageGate`·`RecordingStore` ×2, `FakeCanonicalBroker` ×2·`FakeBrokerSource` ×2·`FakeBroker`·`FakePrivateBroker`, `FakeReviewedGateway`·`FakeReviewedIngress`·`FakeGateway` 계열, `StubHistory`·`StubProvider`, `FakeCatalog`, `FakeShadowStore` ×2, `FakeMaliciousProvider`, `FakeClient` ×2 등 — 라우트 협력자.

**하 87**: `FakeRequest` ×6, `FakeResponse` ×12, `FakeStatement` ×7, `FakeDB`, `FakeQuery` ×2, `FakeBody` ×2, `FakeReader` ×3(응답 셸), `FakeFile`·`FakeFileReader`·`FakeFormData`(5728 사진), `FakeSocket` ×2·`FakeIngress`(WS 셸), `FakeJSBytes`·`FakeJSTypedArray`·`FakeAbortSignalAPI` ×2·`FakeURLSearchParams`(Workers JS 셸), `FakeRecorder`·`FakeAudioContext`(음성 JS), `FakeIdentity` ×2·`FakeCanonicalIdentity`·`FakeWorkspaceIdentity`·`FakeOAuthBinding`·`FakeControlPlaneBinding` ×2·`FakeCanonicalHost`·`FakeCanonicalOwnerAuthority`(신원 셸), `FakeMintPort`, `FakeJob` 등.

## 7. 후속 권고 (별도 작업)

1. **프로토콜·구현 시그니처 불일치**(§2 관찰): `MeshCentralFileReadPort.timeout_seconds` 필수 표기 vs 구현 기본 60 — 운영 결정 후 정렬.
2. chat '상' 저장·인증 가짜(FakeProtectedStore·FakeAuthenticatedCipher·*Store 계열)에 대한 같은 형태의 계약 테스트 확장.
3. file-lane '상' 3건: `_FakeOle`에 실제 OLE 헤더 검증 재사용, ASGI 수제 트랜스포트에 starlette 표준 전송 재사용 검토.
4. 테스트 파일의 BOM(U+FEFF) 1건 발견 — ast 스캔은 utf-8-sig로 방어하되 원본 정리 후보.
5. baseline 기존 실패 1건(`QueueChannelOriginTests`) 별도 확인.
