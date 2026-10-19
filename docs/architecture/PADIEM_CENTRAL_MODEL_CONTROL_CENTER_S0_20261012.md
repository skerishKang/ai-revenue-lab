# PADIEM 중앙 모델 관리자 — S0 구현·권한·수용 경계 (2026-10-12)

관련 이슈: [#4428](https://github.com/skerishKang/ai-revenue-lab/issues/4428) · [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139)

**이번 범위:** B14 → 중앙 정책 → 제품별 서비스의 **단일 관리 UX 첫 단계**, 실제 B14 선택 가능 모델/기존 B66 정책 **읽기 전용 조회** 및 다중 선택 **서버 검증 미리보기**. **실제 모델 배정·삭제·활성화·제품 실행 변경은 구현되지 않았다.**

## 1. 소유권 및 제품 비전

- B14 = **유일한 모델 등록/공급사·API 자격증명/최종 실행 라우터**. B14의 내부 공통 엔진과 독립 **B14 Router 서비스 상품**은 제품별 entitlement가 다를 수 있다.
- 중앙 Control Plane = **제품별 모델 허용·회원 Free/Plus/Pro/Max·상위 제약 정책**. 중앙 글로벌 ON/OFF는 제품별 허용보다 우선하며 기본 거부가 우선.
- Chat·Claw·B66 = **사용자 업무/허용 모델 표시와 정확한 선택 모델 실행**, 제품 고유 기능·도구·P01·견적 안전 검증 유지.
- 중앙 관리자 = 세 영역의 **가시성 + 변경 대상 체크 + 단계적 적용 + 흐름 진단**. 각 영역은 서로 다른 정책을 유지할 수 있으나, 서로의 권위 있는 저장소를 덮어쓰지 않는다. 허용 여부는 B14 readiness ∧ global entitlement ∧ product grant ∧ capability 검증 후 계산해야 한다.
- 동일 모델 ID를 위변조·대체(fallback)/숨긴 provider route로 자동 치환하지 않는다.

## 2. S0 사용자 화면

- 정적 페이지: `/admin-models.html` (PADIEM Chat 정적 배포와 같은 origin, 별도 앱/DB 없음).
- 실제 로그인 후 **독립 글로벌 모델 관리자** 서버 권한 검사; B66 제품 관리자라는 이유만으로 중앙 권한을 부여하지 않음.
- 연결된 B14 owner-allowed/live-ready 모델의 **부분 집합** 표시. **B14 등록 전체 목록으로 표시하거나 모델 20개라고 가정하지 않음**.
- 기존 B66의 실제 D1 `model_policy()`를 안전한 형태로 읽어 제품 정책 소스를 보여줌. D1 없거나 오류면 `unavailable`, Chat/Claw/Control Plane/B14 Router의 운영 정책은 아직 `not_wired`로 표시함. 없는 등급·비용·API readiness를 만들어내지 않음.
- 실제 등록 모델 하나를 선택 → 중앙/Chat/Claw/B66/B14 Router **체크 다중 선택** → Free/Plus/Pro/Max → 허용/차단/상속 변경안 → 서버 검증된 변경안 미리보기. 정확한 모델 ID에 대해서만 preview 허용.
- **S0에는 '변경 적용' API·저장 버튼 없음**. Preview receipt는 `applied:false`, `persisted:false`, `dispatch_authorized:false`이며 화면도 실행에 영향이 없음을 명시.

## 3. 실제 API·인증

| API | 범위 | 변경 |
|---|---|---|
| `GET /api/admin/models/me` | 글로벌 관리자 세션/권한 검증 | 없음 |
| `GET /api/admin/models/snapshot` | 정확한 모델 카탈로그 부분 집합 + B66 D1 제품 정책 조회 | 없음 |
| `POST /api/admin/models/preview` | 정확한 모델 ID와 1~20개의 `product_id/tier/action` 범위 검증 | **없음** |

- 별도 글로벌 role: `D1CentralModelAdminAuthorizer`는 기존 D1의 **Google-verified subject**와 `usr_...` ID 파생값/이메일/비밀번호 계정 부재를 교차 검증한다. 임의 입력 `email`, `admin`, `tier`로 관리자 인증 불가. **B66 권한 메서드 `is_google_admin`을 호출하거나 B66 관리 등급을 글로벌 역할로 간주하지 않음**.
- Worker 전용 명시적 설정 `PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL`이 있을 때만 해당 독립 Role을 바인딩한다. **설정이 없으면 503 `central_admin_not_configured` — 기본 OFF**. 운영 비밀 환경변수 값을 소스·브라우저·로그에 넣지 않음.
- 회원 세션 없으면 401, 독립 글로벌 권한 없으면 403, D1/Resolver 실패면 503. `Cache-Control: private, no-store`, 범위 없는 query 거부, 모델 목록 duplicate/형식/크기 검증, body 8 KiB 제한, 제품과 등급 고정 어휘, 중복 target 거부. 값은 `textContent`로만 표시.
- B14 `b14_model_choice_resolver.list_selectable_models`가 제공하는 subset만; 사용권·가용성 전체 인증으로 과장하거나 API key를 노출하지 않음.
- 기존 B66 회원 정책 PUT는 변경하지 않음. 기존 B14·Chat·Claw 실행 경로를 새 preview 값으로 덮어쓰지 않음.

## 4. 앞으로 필요한 S1/S2 구현

1. **Global RBAC 및 관리자 관리:** 초기 명시적 Google 관리자 → 중앙 글로벌 역할 정책·감사·철회·2단계 승인·회원 등급 관리. 허가된 운영 Secret 등록이 필요하며 현재 Worker 배포 적용 증거는 없음.
2. **공통 모델 정책 저장·리비전:** Control Plane 정규 `padiem_routing_profile_admin` staged diff/approval/revision/rollback 계약과 연계. 제품별 B66 D1의 기존 버전/모델 OFF와 충돌 없도록 **전환 어댑터** 필요.
3. **B14 전체 등록+가용성 카탈로그:** 별도 operator-safe 읽기 인터페이스. 기존 `list_selectable_models`는 등록 모델 전체가 아닌 선택 가능 목록이므로 구분.
4. **제품별 정책 배선:** Chat/Claw/B66/독립 Router에 서버 측 유효 모델 목록·등급·특수 기능 판정과 **최종 B14 실행 직전 재검증**. 정확한 모델 identity, 정책 revision, product, owner/workspace 및 차단 이유 감사. 제품은 서로 다른 설정 유지.
5. **체크 다중 저장:** scope별 변경 diff → 예상 효과 및 충돌 검증 → 관리자 확인 → 명시적 apply → D1 영수증/감사 → 필요시 rollback. 일부 제품 업데이트 실패를 성공으로 보고하지 않음. 취약한 원자성/충돌을 무시한 **일괄 boolean 플래그** 금지.
6. **모델 흐름 추적:** `request → product → central policy → B14 router → provider response`의 비용·사용량·오류 사유(자격증명·고객 대화는 마스킹). 계층별 state/provenance/effective state 구분.

## 5. 수용 증거

- 로그인·권한 기본 OFF, 타 사용자 403, 미구성 503
- B14 카탈로그 부재/중복/변조 503
- 기존 B66 D1 정책 조회 / 없는 제품 데이터 `not_wired`
- 정확한 모델 ID에만 검증 미리보기 / 여러 제품·등급·작업 / 미리보기 후 정책 무변경
- Chromium 데스크톱 1440px + 모바일 390px, 접근 차단 UI
- 기존 B66/Chat/Claw 테스트 영향 검사, exact-head CI.

**운영 변경 상태: OFF.** 현재 PR의 CI/소스 병합은 중앙 관리자가 실제 운영 모델을 저장·재배정할 수 있다는 뜻이 아니다.
