# B66 관리자 화면 분리 및 회원 상세 (2026-10-12)

## 사용자 요청

기존 한 페이지에 모두 노출되는 관리자 UI를 4개 독립 화면으로 분리한다.
- `/admin.html`: 회원 관리·등급 편집 (Free / Plus / Pro / Max), 검색과 가입 승인
- `/admin-models.html`: B14 등록 모델별 전체 ON/OFF, 그룹별 허용 권한
- `/admin-notices.html`: 신규 회원가입 알림·대기·재전송
- `/admin-member.html?id=<usr_id>`: 회원 이메일 클릭으로 접근하는 회원 상세

모든 화면은 서버에서 `/api/b66/admin/me`로 Google 관리자 권한 확인이 되기 전까지 내용을 표시하지 않는다. 회원 상세 데이터는 `GET /api/b66/admin/members/{user_id}/detail`에서 별도 검증한다. 사용자 ID는 기존 `usr_[a-f0-9]{32}` 형식만 허용하며 일반 회원·비로그인·다른 사용자 접근은 403/401이다.

## 회원별 사용내역의 실제 데이터 기준

- AI 요청 오늘 / 7일 / 30일: 기존 `live_usage_buckets`의 `subject_type='user', subject_key=<user id>, bucket_type='day'` 합계. 이 테이블은 **전체 PADIEM Chat의 요청 할당량 카운터**이고 **B66만의 완료된 AI 응답이나 실제 모델별 이용 횟수가 아니다**. 화면에 이 차이를 표시한다.
- 최근 저장 견적: `b66_quote_history`에서 건수와 날짜만 조회한다. 수신인/회사명/금액/스냅샷/첨부파일/AI 메시지 내용은 조회·전송하지 않는다.
- 회원 변경 이력: `b66_membership_audit`에서 상태·등급의 전후 값과 변경 시점만 조회한다.
- 모델별 호출 횟수: 현재 영속 기록이 존재하지 않아 **집계 불가**라고 표시한다. 임의의 0이나 성공률·토큰을 만들어 표시하지 않는다. 새 로깅을 도입하려면 별도 데이터 정책과 마이그레이션 필요.

## 변경 범위와 배포

정적 4페이지 HTML, 공통 관리자 JS/CSS, 읽기전용 관리자 상세 API, Pages Worker 경로 allowlist, 기존 컨트롤러 연결. 기존 모델 ON/OFF, 회원 승인·변경, 알림 발송 설정, QuoteCore/PDF/Google Drive/세션 토큰/모델 공급사 키 변경 없음. 신규 D1 migration 불필요.

검증: PC·모바일 각 4페이지 URL, 서버 관리자 vs 비관리자 접근 차단, 비밀 견적 내용 비노출, 기존 B66 정적 계약 및 B62 backend CI. 기존 B62 backend + B66 Pages 운영 배포를 정확한 main SHA에서만 실행하며, 사후 QA에서 직접 새 페이지 URL을 호출해 확인한다.
