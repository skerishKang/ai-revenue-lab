# B66 및 공통 문서 처리 임의 제한 조사 — 2026-10-20

## 대표 최신 지시
- 정상적인 문서의 2MiB 원본 / OOXML 개별 항목 1MiB / 전체 압축 해제 8MiB 거부를 제거한다.
- 100MB를 초과하는 실제 문서를 수용한다. 초기 문서 용량 목표는 약 1GiB다.
- 저용량 고정 상한만 변경해서 전체 파일을 RAM에 적재하는 구현은 피하고 파일 기반 처리를 우선한다.
- 테스트를 추가 실행하지 말라는 최신 지시를 따른다.

## 확인된 현행 제한 — 최신 main 소스 경로 기준
| 영역 | 제한값 또는 처리 | 위치 | 후속 |
|---|---|---|---|
| B66 generic XLSX 원본 | 종전 2MiB; 이 브랜치에서 1GiB로 변경 | `tools/b66_generic/analyze.py` | 다른 진입 경로와 구분 |
| B66 generic 압축 해제 개별 항목 | 종전 1MiB; 이 브랜치에서 1GiB로 변경 | 동일 | XML 전체 DOM 파싱 메모리 확장성 검토 |
| B66 generic 압축 해제 전체 | 종전 8MiB; 이 브랜치에서 1GiB로 변경 | 동일 | 서버/로컬별 실행 메모리와 디스크 예산 확인 |
| B66 generic ZIP 파일 읽기 | #5274에서 임시 파일 기반 스냅샷으로 변경 | 동일 | 1GiB XLSX 실제 E2E 미확인 |
| Core 원본 바이너리 | 2MiB | `packages/padiem-ai-core/padiem_ai_core/document_normalization.py` | byte-array API를 디스크/스트림 기반으로 별도 개편 |
| Core 텍스트 문서 | 96KiB | 동일 | 일반 문서 길이의 임의 거부 여부 검토 |
| Core OOXML 개별/전체 | 1MiB / 8MiB | 동일 | 정상 대형 문서 수용 정책 조정 |
| Core OOXML 개수 | 256 | 동일 | 문서 시트/관계 파일 많은 경우 거부 |
| Core PDF 페이지 | 80 | 동일 | 대형 PDF 정상 업무 지원 검토 |
| Core XLSX 시트/행/열/비어 있지 않은 셀 | 20 / 500 / 50 / 5,000 | 동일 | 문서 추출 단계의 무단 잘림 또는 거부 확인 |
| Engine 저장 문서 | Core 2MiB 동기화 | `apps/padiem-ai-engine/app/document_byte_store.py` | 저장/전송 Base64, 스토리지 용량 등과 함께 개편 |
| Chat 문서 첨부 | Core 2MiB 동기화 | `apps/padiem-chat/app/binary_documents.py`, `app/ooxml_stdlib.py` | HTTP 요청/파일 저장 기반 아키텍처 고려 |
| Chat 텍스트 파일 | Core 96KiB | `apps/padiem-chat/app/documents.py` | 대형 텍스트 지원 |
| KAgent 파일 수용 정책 | 2MiB 원본 / 1MiB 개별 / 8MiB 전체 | `apps/korean-ai-code-agent/src/kagent/file_intake_safety.py` | 파일 기반 검증으로 변경 |
| KAgent 격리 파서 전송 | Base64에 종전 2MiB 기준 적용 | `apps/korean-ai-code-agent/src/kagent/document_parser_contract.py`, `document_parser_isolation.py` | 큰 데이터를 JSON/Base64로 이동하지 않도록 별도 전송 계약 |
| B66 템플릿 읽기 | ZIP 512개 항목 | `apps/padiem-chat/app/b66_template_source.py` | 템플릿별 필요성 검토 |
| Engine Drive 소비 | Core 텍스트 크기 96KiB | `apps/padiem-ai-engine/app/drive_case_folder_consumer.py` | 대형 문서 수용 |
| Engine PDF 브라우저 | Core PDF 80쪽 | `apps/padiem-ai-engine/app/drive_case_pdf_browser_bridge.py` | 대형 PDF 지원 |

## 실제 완료와 미완료 구분
- **기병합:** PR #5272 테스트 전용 1MiB 메모리 피크 절대 상한 제거; PR #5274 B66 소스 임시 파일 스냅샷 도입.
- **현재 변경 브랜치:** `cto/b66-1g-document-bounds-4379`의 `analyze.py`에 B66 전용 1GiB 용량 기준 적용. 종전 작은 값을 가정한 관련 테스트는 회귀 계약 정합화만 수행.
- **변경 전 관측:** 로컬 집중 42건 성공, 약 110MB 원본 XLSX 한 건 분석 성공. 대표의 이후 '테스트하지마' 지시 이후 **추가 실행 테스트 중단**. 이 관측은 1GiB 완료 검증이 아니다.
- **미완료:** Core/Chat/Engine/KAgent의 임의 파일·추출 한도 조정, 대용량 파일의 메모리 안전한 파싱, 제품 배포, 1GiB 운영 E2E.
- ZIP 경로 탐색, 중복 멤버, 암호화된 파일, 비정상 구조 검증은 용량 제한과 구별해 추적한다.

## 추적
- 기존 전체 정책 이슈: #4379
- COM2 CI 이전 이슈: #5210 (별도)
- 후속 PR: B66 1GiB 분석기 변경은 위 브랜치 PR에서 추적
