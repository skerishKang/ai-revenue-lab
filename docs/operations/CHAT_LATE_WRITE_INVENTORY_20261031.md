# Chat COM2 이전: 늦은 쓰기 분류표 (진행 중)

기준: `4d61bc0a67769fee90d5a25e0d7d5edf5b0370d8`에서 시작, `094d9430f` main 병합. 이 표는 전체가 아니다. HTTP 저장소 호출 및 cron·queue·WSS·waitUntil의 추적이 끝나기 전 전환 허가 근거로 사용하지 않는다. 코드 줄 번호는 이 브랜치 기준이다. 운영 데이터 조회 없음.

## 쓰기 효과가 확인된 GET (4개 진입점, 일부 후속 호출의 표는 추가 조사 필요)

| 진입점 | 저장소 함수 | 대상 표 | 실행 | 근거 |
|---|---|---|---|---|
| GET `/auth/google/callback` | `D1HistoryStore.upsert_google_user` | `users` | 응답 전 await, 성공 경로 조건부 | `apps/padiem-chat/app/app_factory.py:569`, `app/auth_routes.py:526`, `app/history.py:1082`, `app/history.py:1089`-1094 |
| GET `/auth/lovetree/start` | `D1LoveTreeLoginHandoffStore.create` | `lovetree_login_handoffs` | 응답 전 await | `apps/padiem-chat/app/app_factory.py:578`, `app/lovetree_auth_routes.py:141`, `app/lovetree_auth_store.py:215`, `:231` |
| GET `/api/connectors/github/start` | `D1GitHubOAuthStore.begin` | `claw_github_oauth_states` | 응답 전 await | `apps/padiem-chat/app/app_factory.py:603`, `app/github_oauth_routes.py:60`, `app/github_oauth_store.py:39`, `:44` |
| GET `/api/connectors/github/callback` | `D1GitHubOAuthStore.consume`, `save` | `claw_github_oauth_states`, `claw_github_connections` | 응답 전 await, 단계별 조건부 | `apps/padiem-chat/app/app_factory.py:604`, `app/github_oauth_routes.py:96`-102, `app/github_oauth_store.py:48`-51, `:70`-73 |

Google callback은 `auth_routes.py:532`, `:558`, `:562`, `:567`, `:575`의 추가 세션·가입 전달·handoff 호출도 있으므로 위 `users`만으로 쓰기 범위가 완전하지 않다. GitHub 자격증명 갱신 호출자(`github_oauth_routes.py:125`-130)의 GET 연관 여부도 미확인이다.

## 응답 이후 / 백그라운드: 조사 중

| 진입점 | 저장소 함수·대상 | 실행 | 근거 및 상태 |
|---|---|---|---|
| 요청 텔레메트리 내보내기 | 내보내기 대상 추적 필요 | `waitUntil` 스케줄 | `app/request_telemetry.py:420`-434, `worker.py:1844`-1864. **D1 쓰기로 확인되지 않음** |
| Worker scheduled / 로컬 cron | `run_scheduled_automation_source` → automation store 등; 개별 SQL·표 추적 필요 | 백그라운드 await | `worker.py:228`, `:256`, `:287`, `:331`, `:1048`-1050; `app/local_cron.py:1`-3 |
| WSS connector gateway | 진입과 downstream 저장소·표 추적 필요 | 장시간 연결 | `app/canonical_connector_gateway_source_composition.py:80` |
| queue / 외부 producer | 진입점·대상·정지 절차 미확인 | 비동기 | 미확인; 별도 권위 queue가 있어 Chat D1 범위와 구분 필요 |

## 수정 제안

- 쓰기 효과가 있는 GET도 쓰기 정지 분류에 포함하고 전환 창에 fail-closed 처리한다. 인증 흐름 변경은 별도 설계·검증한다.
- cron, 장시간 WSS, 큐와 `waitUntil` 작업을 각 권위별로 중지하고 진행 중 작업 완료를 독립 증거로 확인한다.

## 한계와 미완료

스냅숏 비교는 정지 창 안에서 생겼다가 되돌려진 쓰기를 잡지 못한다. 따라서 분류표로 위험 경로를 미리 막는 것이 본 대책이다. `.github/scripts/chat_d1_handback_gate.py:snapshot`은 표별 기본키·행 다이제스트를 제공하나 queue·broker·시스템 표를 제외하므로 그 비교 결과는 제외 범위의 무쓰기를 증명하지 않는다. 두 시점 비교도 독립적인 드레인 증거를 대체하지 못한다.

전체 저장소 SQL을 진입점까지 역추적하는 작업, 4개 GET의 모든 부수 쓰기, 응답 후 실행 경로 및 대상 표의 확인은 미완료다. 수치는 확인된 진입점 수이며 전체 개수가 아니다.
