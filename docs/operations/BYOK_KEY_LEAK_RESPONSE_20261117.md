# BYOK 키 유출 대응 절차 (#5824)

이 문서는 사용자가 등록한 API 키(이하 "내 API 키")가 유출되었을 때 해야 할 일과
우리 쪽 확인 절차를 정리한다. 키·토큰의 **원문 값은 이 문서와 이슈·PR·로그에
적지 않는다.** 필요하면 키 앞부분 형태나 마지막 네 자리 같은 식별 정보만 쓴다.

## 즉시 조치 — 사용자가 할 일

1. **서비스에서 키 삭제**: 설정 → `내 API 키` → `삭제`.
   - 실제 경로: `DELETE /api/chat/custom/credential?provider=<공급사>`
   - 구현: `apps/padiem-chat/app/byok_routes.py::custom_credential_delete`
   - 저장소에서 행을 지운다: `apps/padiem-chat/app/byok_credentials.py`
     `D1CustomProviderCredentialStore.delete()` →
     `DELETE FROM chat_custom_provider_credentials WHERE user_id=? AND provider_id=?`
   - 삭제 직후 화면은 `custom_credential_required`(키 먼저 등록) 상태가 된다.
2. **키를 발급한 곳에서 폐기(revoke)**: 서비스 삭제만으로는 공급사 측 키가 살아 있다.
   반드시 해당 공급사 콘솔에서 키를 폐기해 새 호출이 막히게 한다.
3. **교체가 필요하면**: 같은 `내 API 키` 화면에서 새 키를 등록한다.
   `PUT /api/chat/custom/credential`은 `ON CONFLICT(user_id, provider_id) DO UPDATE`로
   기존 행을 덮어쓴다(`D1CustomProviderCredentialStore.save`). 별도의 회전 API는 없다.

## 우리 쪽 확인

### 1. 호출 장부 기록 조회

- BYOK 호출은 B14 호출 장부에 `credential_source=user`로 남는다.
  (`apps/korean-ai-platform/app/pilot/call_ledger.py`의 `CREDENTIAL_USER`,
  `gateway.py`의 user-source 기록)
- 조회 경로: `GET /v1/admin/model-calls`, `/aggregate`, `/{log_id}`
  (`apps/korean-ai-platform/app/pilot/call_ledger_admin.py`).
  소유자 범위로 읽히며, 장부가 붙지 않았으면 "기록 없음"을 성공으로 해석하지 않는다.
- 확인점: 키 삭제·폐기 시각 이후 동일 소유자·공급사의 신규 user-source 호출이 0건인지.

### 2. 봉인 저장 삭제 확인

- `chat_custom_provider_credentials`에서 해당 `user_id` + `provider_id` 행이 없어야 한다.
  확인은 `custom_credential_status`(`GET /api/chat/custom/credential`)로도 할 수 있다.
- 키는 소유자+공급사+엔드포인트 바인딩 AAD로 봉인되어 있다
  (`byok_credentials.py::D1CustomProviderCredentialStore`, endpoint-bound AAD v3,
  CPython 봉인 이식 #6497). 행이 남아 있으면 복호화 키 회전 링으로 재봉인되어 있을 수
  있으므로, 삭제 여부는 행 유무로 판정한다.

### 3. 로그·응답·아티팩트에 키가 없는지

- 응답은 키 원문을 반환하지 않는다. `byok_routes.py`는 저장 후 키를 다시 읽지 않고
  메타데이터만 노출하며, `Cache-Control: no-store`를 붙인다.
- 참고 시험(키 값이 로그/응답에 없음을 이미 증명):
  - `apps/korean-ai-platform/tests/test_5824_b14_user_credential.py::test_the_credential_value_never_reaches_a_log_line`
  - `apps/padiem-chat/tests/test_5121_multi_provider_byok.py`(탐침·등록 응답과 caplog에 키 없음)
  - `apps/padiem-chat/tests/test_5824_byok_probe_limit.py`(제한 응답·로그에 키 없음)
- 점검 방법: 사고 구간의 서버 로그, 이슈/PR 본문, 테스트 아티팩트에서 키 값 대신
  **접두사 형태와 마지막 네 자리**로 검색한다. 원문을 검색어로 붙여넣지 않는다.

### 4. 남용 흔적 확인

- 키 확인(탐침/연결 테스트) 호출은 소유자당 시간당 10회로 제한되어 있다
  (`apps/padiem-chat/app/byok_probe_limit.py`, `429 byok_probe_rate_limited`).
  사고 시각에 이 제한이 초과되는 패턴이 있는지 장부와 함께 본다.

## 연락 경로

- 신고: 이 저장소 이슈 트래커에 보안 건으로 남기고, 키 원문·토큰·계정 비밀번호는
  본문에 넣지 않는다. 공개 이슈가 부적절하면 저장소 관리자에게 직접 알린다.
- 긴급 대응(호출이 계속 나가는 등)은 대표/운영 담당자가 지정한 별도 채널로 즉시 통보하고,
  위 "즉시 조치" 1~2번을 먼저 실행한다.
- 사후 기록: 조치 시각, 삭제 확인 결과, 장부 조회 결과만 남기고 키 값은 남기지 않는다.

## 범위 밖

- 키별 지출 상한과 팀 공유는 현재 범위에서 제외되어 있다(#5824 11-12 범위 정리).
- 공급사 경유 정책과 직접 호출 fallback 정리는 대표 결정 대기 상태다.
