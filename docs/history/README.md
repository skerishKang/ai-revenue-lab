# 역사 기록 및 증거 안내

~~~text
DOC_STATUS = CANONICAL
SCOPE = NAVIGATION_ONLY
~~~

이곳은 **과거 기록의 탐색 인덱스**입니다. 원본 파일은 기록 당시의 내용 그대로 보존하며, 현재 제품·모델·정책의 승인 근거로 자동 승격시키지 않습니다. 현재 우선순위는 [Documentation Authority Model](../governance/DOCUMENTATION_AUTHORITY_MODEL.md)을 따릅니다.

## 역사 자료 분류

| 종류 | 해석 방법 | 보존 파일 |
|---|---|---|
| 아키텍처·소유권 감사 | 특정 리비전의 설계·책임 경계 검증 기록 | [2026-09-01 소유권 감사](2026-09-01/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.audit.md) |
| 공통 실행 계층의 과거 README | 과거 Core 구현과 문서의 모습. 현재 Core 권위는 아님 | [2026-09-01 Core 스냅샷](2026-09-01/PADIEM_AI_CORE_README.snapshot.md) |
| 사업별 과거 README | 해당 시점 Claw 제품 설명. 현재 B54의 승인 문서가 아님 | [2026-09-02 Claw 스냅샷](2026-09-02/PADIEM_CLAW_README.snapshot.md) |
| 견적서 실험·방법론 | 과거 B66 설계와 개발 추론의 스냅샷 | [2026-10-08 개발 모델 휴리스틱](2026-10-08/B66_DOCUMENT_FIDELITY_DEVELOPMENT_MODEL_HEURISTICS.snapshot.md), [실행 복구 기록](2026-10-08/B66_MVP_RUNTIME_REPAIR_2026-10-08.snapshot.md) |
| 견적서 구현·데모 문서 | 예전 어댑터, 참조 구현, 데모 안내의 원문 | [어댑터 README](2026-10-08/B66_QUOTE_SERVER_ADAPTER_README.snapshot.md), [참조 README](2026-10-08/B66_QUOTE_BETA_REFERENCE_README.snapshot.md), [DEMO GUIDE](2026-10-08/B66_QUOTE_BETA_DEMO_GUIDE.snapshot.md) |

위 링크는 기존 보존 파일의 탐색을 돕기 위한 것으로, 별도의 운영 승인·배포 기록을 만들지 않습니다. 새로운 증거가 추가될 때에는 새로운 날짜·파일·이슈·PR을 식별하고, 기존 원본을 덮어쓰지 않습니다.

## 역사 자료를 읽는 순서

1. **현재 사실 확인:** 사업은 [사업별 안내](../businesses/README.md), 공통 규칙은 [공통 안내](../common/README.md), 모델은 [모델 안내](../models/README.md), 검증은 [증거 인덱스](../evidence/README.md)에서 기준을 찾습니다.
2. **시점 확인:** 역사 파일의 날짜, PR·이슈, 검증 revision을 기록합니다. 과거 PASS가 현재 HEAD 또는 Production PASS라는 뜻은 아닙니다.
3. **원문 보존:** 원본 이동·삭제·수정은 일반적인 정리 작업에 포함하지 않습니다. 불가피하다면 명시적 승인, 링크 영향 검사, 원본 바이트 보존 근거가 필요합니다.
4. **정정 방식:** 원본 내용을 현대화하지 말고, 별도의 현재 문서 또는 인덱스에서 어느 주장이 더 이상 유효하지 않은지 설명합니다.

[개발 단계별 인덱스](../lifecycle/README.md) · [증거 인덱스](../evidence/README.md)
