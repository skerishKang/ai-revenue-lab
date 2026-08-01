# 09 — Known Limitations and Non-Goals

## 검증 제품 한계 (현재 상태)

```text
backend 0
persistent storage 0
real auth 0
live AI 0
real file upload 0
OCR 0
external integration 0
billing 0
analytics implementation 0
production deployment 0
```

## 상세 한계

- 모든 조직·사람·견적·가격·계약·검토 기록은 합성(Nori Works, fictional)입니다.
- 상태는 브라우저 메모리와 DOM에만 존재합니다. 새로고침 시 초기화됩니다.
- "저장됨"은 브라우저 메모리 저장이며 서버 영구 저장이 아닙니다.
- AI 보조는 합성 상태 머신이며 실제 모델 호출이 아닙니다.
- 증거·검토·승인은 합성 시나리오입니다.

## 비목표

```text
실제 고객·조직 데이터 사용
실제 구매 추천·구매 실행
실제 파일 업로드·OCR
실제 AI 모델/외부 API 호출
인증·권한 서버 구현
지속 저장·감사 서버 구현
결제·요금
분석/수집 구현
프로덕션 배포
```

이 한계는 이후 backend·파일럿 결정 시 각각 별도 승인을 거쳐야 합니다.
