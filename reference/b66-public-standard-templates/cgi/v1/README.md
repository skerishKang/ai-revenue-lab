# 공개 표준 견적 템플릿 — CGI v1 (김범신)

`REFERENCE_LIBRARY_STATUS=PUBLIC_SOURCE_CONTROLLED`

이 폴더는 **사용자가 공개를 승인한 김범신 CGI 표준 견적서 양식**의 버전 관리용 자료입니다. **고객별 작성 견적의 최근 이력이나 고객이 올린 비공개 템플릿 저장소가 아닙니다.**

## 템플릿의 의미

- **김범신 CGI**: 원본 표준 견적서의 양식과 고정된 시각 구조.
- **Sol 6.1**: 같은 CGI 원본에서 만든 결정적 템플릿 구현 (우선 사용 후보). 이 자료를 적용한 새 견적의 PDF 생성에는 Sol/B14 모델을 매번 호출하지 않습니다.
- **GLM 5.3**: 동일 원본을 이용한 **비교 템플릿**. 새 값을 덧씌워도 과거 원본의 거래처·금액이 PDF의 추출 가능한 텍스트로 남는 결함이 확인됐습니다. **고객용 렌더링 금지**.

## 실제 등록된 파일

| 위치 | 용도 | 주의 |
|---|---|---|
| `source/original.pdf` | 소유자가 공개를 승인한 표준 CGI 기준 PDF | 원본 SHA-256 일치 |
| `source/original-public.xlsx` | 공개용 원본 XLSX 정리본 / 양식 참조 | 원본에 존재하던 외부 파일 연결 항목 76개와 로컬 경로·작성자 메타데이터 정리. 원본과 바이트가 다르며 **계산 권위나 인증 원본이 아님** |
| `sol61/template/` | Sol 표준 템플릿의 구조·프로그램·PDF 리소스·출처 시각 자산 | 원본에서 발견된 로컬 경로 2개만 공개판에서 대체 |
| `sol61/engine/`, `sol61/quote-core.js` | 결정적 엔진·필드 치환 코드 | 전용 런타임 절대경로를 시스템 PATH `node`로 변경; 공개판 변경점은 원본 인증과 구별 |
| `sol61/certificate.json` | **보관 중인 원본 전체 패키지**의 인증 증거 | 공개 축약본의 새로운 인증서가 아님 |
| `glm53/` | 원본 이력 텍스트가 남는 GLM 비교 구현 및 PDF | 비교 전용; 실제 고객에게 제공하지 않음 |
| `PUBLIC_RELEASE_MANIFEST.json` | 공개판 18개 파일의 파일별 SHA-256·크기·원본 기준 해시·수정 내용 | `python tests/test_public_bundle_contract.py`로 검사 |

## 원본과 공개판

원본은 수정하지 않고 다음 비공개 영구 보관소에 유지합니다.

```text
E:\PadiemPrivateVault\B66\template-library\cgi\v1-20261009  (SSD 원본)
G:\PadiemPrivateVault\B66\template-library\cgi\v1-20261009  (별도 백업)
```

- 공개판은 **현장 PC 로컬 경로와 문서의 외부 링크를 정리한 파생본**입니다. 따라서 원본 패키지 SHA와 공개판 파일 SHA는 일부 달라집니다. 해시를 섞어 **재인증 완료**라고 주장하지 마세요.
- 서드파티 Windows 시스템 폰트 원본(`.ttf/.ttc/.otf`)은 저작권·재배포 권한 확인 전까지 Git에 포함하지 않습니다. PDF 내부에 이미 포함된 폰트 서브셋과 별도 설치 폰트 라이선스는 다릅니다.
- 인증 범위는 현재 CGI 단일 A4의 품목 **1~3개**입니다. **다중 페이지는 #3839**에서 별도로 구현·검증 중입니다.
- 공개 Git에 있다고 B66 Production 템플릿으로 **자동 등록·배포·활성화되는 것은 아닙니다.** 실제 고객 계정용 템플릿 프로비저닝, R2, Saved Skill 지정, PDF E2E는 별도 승인·증거가 필요합니다.
- 모델은 최초 템플릿 분석/구현 시 사용될 수 있지만, **반복 견적의 금액은 QuoteCore가 계산**하고 PDF는 인증된 결정적 렌더러가 출력합니다.
- **실제 고객이 올린 템플릿·계좌 정보·비공개 로고/도장·가격·견적 원본을 이 공개 폴더에 추가하지 마세요.** 고객별 분리/복구 정책은 [템플릿 보관 정책](https://github.com/skerishKang/ai-revenue-lab/blob/main/docs/products/b66/TEMPLATE_CUSTODY_POLICY.md)과 #3884가 담당합니다.

## 오프라인 검증

```powershell
py reference/b66-public-standard-templates/cgi/v1/tests/test_public_bundle_contract.py
```

이 검증은 외부 모델 호출이나 Cloudflare 변경 없이 파일 해시·구성·금지 확장자·외부 링크 부재를 확인합니다.

### 변경 이력

- 2026-10-09: 공개 표준 CGI 템플릿 등록 승인 (#3883).
- 과거 메타데이터 전용 Draft PR #3838은 당시의 **비공개 보관 결정**에 기초합니다. 현재 Owner의 공개 승인으로 발행 정책이 변경됐습니다. 두 결정을 동일한 것으로 취급하지 마세요.
