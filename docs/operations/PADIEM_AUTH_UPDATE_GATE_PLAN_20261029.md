# padiem-auth 갱신·복구 게이트 설계 초안

상태: NOT READY. 최초 배포가 아직 실패하여 실제 제공 중인 Worker의 바인딩·버전 기준선이 없다. 이 문서는 운영 변경을 수행하지 않으며, 갱신·롤백 실행 워크플로의 대체물이 아니다.

## 확인 및 게이트 계약

- 기준 계정: Charliekant. 문서의 승인 계정 ID와 API 결과를 내부 비교하고 기존 padiem-chat Worker 존재를 읽기 검증한다. 계정 ID와 비밀 값은 출력하지 않는다.
- 입력: 최신 main 40자리 정확 SHA, 작업(readonly/update/rollback), 현재 활성 배포 버전 ID, rollback 대상 버전 ID(rollback 때), 작업·SHA·버전이 묶인 확인 문구. 본인 권한·배포 이력·대상 버전 존재가 불확실하면 중단한다.
- 선행 readonly: 동일 SHA와 동일 활성 버전에 대한 최근 성공을 확인하고, 현재 활성 배포가 여러 버전으로 분할되어 있으면 명시적 지원 전 거부한다. readonly 이후 업데이트·롤백 직전에 활성 버전과 SHA를 다시 읽어 일치하지 않으면 쓰기 0.
- 바인딩 기준선은 최초 배포와 Secret 등록 이후 `/workers/scripts/padiem-auth/settings`의 **이름·종류·비밀 외 목적지**만 검증해 리뷰된 저장소 기준선으로 만든다. Secret 값은 열람하거나 출력하지 않는다. 기준선 부재, 불일치, 중복 이름은 거부한다. 재배포가 기존 변수·Secret·서비스·Durable Object 바인딩을 제거하거나 다른 대상으로 바꾸지 않는지도 배포 전 검증한다. 신규·변경 바인딩은 별도 승인과 기준선 PR을 요구한다.
- 업데이트 전 Worker 코드의 테스트와 dry-run, 성공한 readonly 증거를 확인하고 정확한 SHA를 배포한다. 기존 Secret은 덮어쓰지 않는다. 배포 후 활성 버전·바인딩·JWKS와 기본 꺼짐 경로를 대조한다.
- 롤백은 확인한 과거 버전 ID를 명시해 `wrangler rollback`으로 호출하고 활성 버전과 바인딩을 재확인한다. Durable Object 클래스 변경, 삭제된 리소스 또는 SQLite 데이터 변형은 코드 롤백으로 복원되지 않을 수 있어 사전 호환성 검증이 없으면 거부한다. 운영 장애 시 자동 삭제·데이터 역이관은 하지 않는다.

## 구현을 막는 실제 정보

1. padiem-auth 초기 배포가 실행되지 않아 활성 버전과 실제 바인딩 집합을 얻지 못했다. 예상 이름을 운영 기준선으로 확정하지 않는다.
2. Wrangler dry-run만으로 배포 후 보존될 모든 변수·Secret의 집합을 증명하지 못했다. 저장소 설정과 기존 서비스 결합을 정확히 대조하는 검사를 추가해야 한다.
3. Worker 코드·바인딩 롤백과 별개인 Durable Object 데이터 호환성 및 기기별 검증이 필요하다.
4. 자동 실행되지 않는 draft PR에서 게이트 구현·합성 실패 사례 테스트·CTO 검토를 마친다. 현재 파일은 기능이 아니라 작업 계획이다.

## 최초 배포 후 확인 — 2026-10-29

COM1의 기존 OAuth로 승인 계정의 활성 배포가 단일 버전임을 확인했다. 해당 버전의 이름·종류만 읽은 결과 `AUTH_STATE`(durable_object_namespace), `IDENTITY_AUTHORITY`(service), `PADIEM_AUTH_ES256_PRIVATE_JWK`·`PADIEM_AUTH_IDENTITY_HMAC_KEY`·`PADIEM_AUTH_REFRESH_ENCRYPTION_KEY`(secret_text), `PADIEM_AUTH_JWKS`·`PADIEM_AUTH_SIGNING_KID`(plain_text)가 있다. 값과 버전 ID는 기록하지 않았다. Google client secret 및 서비스별 설정은 이후 별도 단계라 이 목록을 최종 기준선으로 확정하지 않는다.

갱신 게이트는 어떤 모드에서도 `bootstrap-deploy.mjs`를 호출하거나 서명·지문·refresh 키를 재생성하지 않는다. 같은 코드의 dry-run과 업데이트는 기존 Secret을 보존하고 일반 vars 보존(`--keep-vars`)과 전후 기준선을 검증해야 한다. 단순한 이름·종류 검사를 충분한 안전성으로 취급하지 않는다. 실제 구성과 계획된 업로드의 동등성, 부재/추가 바인딩, 대상 리소스, 활성 버전 변화에 대한 fail-closed 테스트가 남았다.
