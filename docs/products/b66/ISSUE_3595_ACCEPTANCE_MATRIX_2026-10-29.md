# #3595 수용 항목 ↔ 현재 main 대조표 (2026-10-29)

```text
DOC_STATUS = READ_ONLY_EVIDENCE_MAP
OWNER = B66 product
CERTIFICATION_AUTHORITY = #3595 (이 문서는 그 권위를 대체하지 않는다)
PRODUCTION_MUTATION = NO
DEPLOY = NO
```

이 문서는 [#3595](https://github.com/skerishKang/ai-revenue-lab/issues/3595) 본문의 수용 플래그를 **하나씩 현재 `main` 코드와 대조**한 결과만 적는다. 판정은 세 가지다.

- `PASS` — 이 저장소에서 근거를 찾을 수 있고, 재현 절차가 있다.
- `PARTIAL` — 일부만 있다. 무엇이 비었는지 같은 줄에 적는다.
- `NOT_DONE` — 없다.

`PARTIAL`/`NOT_DONE`은 이슈를 닫지 않는다는 뜻이며, 마지막 절의 작은 후속 PR 후보가 정확히 그 빈칸이다.

## 0. 현재 CGI/2번째 양식 증거의 위치

```text
GENERIC_PIPELINE = tools/b66_generic/{analyze,compile_generic,render,certify,validate_mutations,literal_scan}.py
RECORDED_EVIDENCE = tools/b66_generic/evidence/{certification,second_template_certification_summary}.json
PUBLIC_REGRESSION = tools/b66_generic/tests/test_b66_generic_{compile,archive_bounds}.py (합성 양식, 고객 사실 없음)
PRODUCT_EXECUTION = apps/padiem-chat/app/b66_certified_{pdf_routes,preview,quote_bundle,quote_bundle}.py + b66_saved_quote_skill_store.py
```

2번째 양식은 **실제 사설 견적서**로 인증됐지만 그 원본·고객 값은 커밋되지 않는다(해시·게이트 결과만). 저장소의 공개 회귀는 무관한 합성 양식으로 같은 코드 경로를 재실행한다.

## 1. 아키텍처·수명주기 수용 항목

| 항목 | 현재 main 근거 | 판정 | 빈칸 |
| --- | --- | --- | --- |
| `ANALYSIS_AND_REPRODUCTION_SEPARATE=YES` | `analyze.py`는 READ-ONLY 관찰 JSON만 만들고(의미 부여 없음), `compile_generic.py`가 라벨 앵커·기하 탐지로 슬롯을 파생. 두 단계 산출물이 분리 저장된다. | PASS | — |
| `REPRODUCTION_BEFORE_EXECUTION=YES` | `render.py`가 참조 사실로 재현 PDF를 만들고, `certify.py`가 기준 PDF와 비교한 뒤에만 승인 번들(`manifest.certification.status == "PASS"`)이 만들어질 수 있다. 제품 실행 경로는 승인 번들 없이는 렌더러에 도달하지 못한다. | PASS | 도구 체인 수준. 제품 측 승인 절차는 §4 참조. |
| `REFERENCE_PDF_ORACLE_REQUIRED=YES` | `certify.py --baseline <reference pdf>`가 필수 인자이고 페이지/폰트/자산/래스터 비교의 기준이다. | PASS | — |
| `CERTIFICATION_STATE_PERSISTED=YES` | 두 곳에 나뉘어 있다. ① `b66_template_source.status`는 `CHECK (status IN ('uploaded','disabled'))` — 인증 상태를 담지 않는다(migration 060). ② 번들 manifest는 `certification.status == "PASS"` 단일 비트만 요구한다(`b66_certified_quote_bundle.parse_bundle`). | **PARTIAL** | 이슈가 요구하는 5단계 상태(`ANALYZED`/`REPRODUCTION_IN_PROGRESS`/`CERTIFIED`/`CERTIFIED_WITH_TOLERANCE`/`REJECTED`)와 허용 오차 기록 필드가 어디에도 영속되지 않는다. |
| `UNCERTIFIED_NEW_TEMPLATE_EXECUTION=DENIED` | `parse_bundle`은 manifest 키 집합·schema·`saved_skill_id`·`skill_fingerprint`·`profile_fingerprint`·`certification.status`·렌더러 계약/엔진 버전/소스 해시를 모두 대조하고 어긋나면 `B66CertifiedQuoteBundleError`로 거절한다. 라우트는 승인된 Saved Quote Skill 배정(`_approved_profile`)까지 확인한다. | PASS | 오늘의 거절은 **이진 PASS** 기준이다(위 `PARTIAL`과 같은 뿌리). |
| `SOURCE_REANALYSIS_PER_REPEAT=0` | `b66_certified_pdf_routes.py`/`b66_certified_preview.py`는 `b66_template_source`·분석 산출물을 읽지 않는다. 반복 출력은 승인 번들 + QuoteCore 값만 쓴다. | PASS | — |

## 2. 증거 수용 항목 (2번째 양식 기준)

게이트는 `certify.py`가 이름별로 따로 보고한다. 아래는 그 게이트가 실제로 무엇을 재는지까지 적는다.

| 항목 | 게이트 / 근거 | 판정 |
| --- | --- | --- |
| `PAGE_GEOMETRY_REVIEWED=YES` | `PAGE_GEOMETRY`(페이지 rect), `PAGE_COUNT` — 기준 PDF 대조 | PASS |
| `TEXT_GEOMETRY_REVIEWED=YES` | `TEXT_POSITION`(스팬별 x,y) | PASS |
| `FONT_IDENTITY_REVIEWED=YES` | `FONT_FAMILY`(스팬 폰트 집합 비교) | PASS |
| `TYPOGRAPHY_METRICS_REVIEWED=YES` | `FONT_SIZE`, `TEXT_SPACING_BASELINE`(스팬 튜플 전체 비교) | PASS |
| `LOGO_GEOMETRY_REVIEWED=YES` | `LOGO_GEOMETRY` | PASS (단, 아래 별칭 주의) |
| `STAMP_GEOMETRY_REVIEWED=YES` | `STAMP_GEOMETRY` | PASS (단, 아래 별칭 주의) |
| `STAMP_ALPHA_LAYERING_REVIEWED=YES` | `STAMP_ALPHA`(bbox+alpha), `ASSET_LAYERING` | PASS (단, 아래 별칭 주의) |
| `TABLE_LINE_GEOMETRY_REVIEWED=YES` | `TABLE_LINES_BORDERS` | **PARTIAL** — 아래 별칭 주의 |
| `REFERENCE_VALUE_PARITY=YES` | `REFERENCE_VALUE_PARITY` + `_detail`(견적번호/수신처/건명/작성일 serial/품목) | PASS |
| `RASTER_DIFF_MEASURED=YES` | `RASTER_SIMILARITY` 72/150/300dpi, 기록값 0/0/0 | PASS |
| `CRITICAL_GATES_NOT_REPLACED_BY_AGGREGATE_DIFF=YES` | `certify.py`는 게이트 14개를 각각 보고하고 래스터는 별도 키로만 쓴다. 래스터가 0이어도 다른 게이트가 false면 `SECOND_TEMPLATE_CERTIFICATION=FAIL`. | **PARTIAL** — 아래 별칭 주의 |
| `MUTATION_ROBUSTNESS_REVIEWED=YES` | `validate_mutations.py`: 변경 슬롯의 **자기 cover rect**에서 허용 영역을 유도하고 그 밖 픽셀 변화 0을 요구. 기록된 2번째 양식 결과 `14 케이스 / PASS 11 / REJECTED 3 / FAIL 0`, `MAX_OUTSIDE_ALLOWED_CHANGED_PIXELS=0`. | PASS |

### 별칭(alias) 주의 — 왜 위 세 줄이 `PARTIAL`인가

`certify.py`에서 게이트 이름은 14개지만 **측정식이 겹치는 이름이 있다.**

```text
TABLE_LINES_BORDERS = gates["LAYOUT_GEOMETRY"]      # 같은 drawings 비교를 이름만 바꿔 재사용
WRAP_SHRINK         = s1 == s2                      # TEXT_SPACING_BASELINE 과 같은 비교
LOGO_GEOMETRY = STAMP_GEOMETRY = ASSET_LAYERING = (i1 == i2)   # 이미지 목록 동일성 비교 하나
```

기준 재현에서는 값이 같아도 무방하지만, 이슈가 요구한 "임계 요소별 독립 검토 가능"에는 못 미친다. 줄/테두리, 감김/축소, 로고/도장/레이어링을 **각각 다른 관측**으로 나눠야 그 세 줄이 `PASS`가 된다. 현재 이 항목들의 실제 안전망은 래스터 0과 변이 케이스(감김 경계 포함)이며, 그 둘이 대체 검증이라는 사실 자체를 여기 기록한다.

## 3. 허용 오차 수용 항목

| 항목 | 현재 main 근거 | 판정 |
| --- | --- | --- |
| `SILENT_APPROXIMATION_ACCEPTANCE=NO` | 제품 경로는 `certification.status == "PASS"`만 받는다. "대충 비슷함"을 통과시키는 점수 임계값 경로가 없다(래스터도 `== 0` 요구). | PASS (구조적으로 불가능) |
| `USER_ACCEPTED_DEVIATION_RECORDED=YES_IF_USED` | 쓸 수 있는 자리가 없다(아래 상태 미구현). | `NOT_USED` |
| `CERTIFIED_WITH_TOLERANCE_EXPLICIT=YES_IF_USED` | 5단계 상태·오차 기록 스키마가 코드에 없다. | **NOT_DONE** |

## 4. 이슈 밖/별도 트랙 (닫힘 판단에 섞지 않는다)

```text
#3839 4+ 페이지(멀티페이지) 인증        = PARKED (별도 이슈)
#3884 고객 원본 private custody         = OPEN (업로드만; status='uploaded')
#4106 형식별(XLSX+PDF/HWPX) 충실도 인증 = OPEN (정책 문서만 완료)
#3444 정밀 재검수 백그라운드 계획        = 기획으로 흡수, 인프라 미승인
2번째 양식 계정 수준 실행 여정           = NOT_DONE (benchmark 인증 ≠ 고객 여정 증명)
```

2번째 양식은 **도구 체인 인증**이다. 실제 고객 계정에서 그 양식이 배정→입력→미리보기→PDF로 도는 것은 아직 아무도 증명하지 않았다. 이 구분을 흐리면 "#3595 완료"가 거짓이 된다.

## 5. 빈칸 → 작은 후속 PR 후보

1. **게이트 별칭 분리** (`tools/b66_generic/certify.py`) — `TABLE_LINES_BORDERS`(stroke/vector 전용 측정), `WRAP_SHRINK`(감김·축소 경계 슬롯 전용), 로고/도장/레이어링을 자산 종류별로 나눠 각각 보고. 기존 14게이트 이름과 기록값은 유지하고 측정식만 분리.
2. **인증 상태 영속** — 5단계 상태 + 허용 오차 기록. 번들 manifest는 `_MANIFEST_KEYS` 완전 일치를 요구하므로 필드를 그냥 더하면 **기존 승인 번들이 전부 거절**된다. 스키마 버전을 올리는 별도 슬라이스로만 가능(마이그레이션 필요 시 다음 번호 080, 테이블 재빌드 금지).
3. **파이프라인 회귀를 CI에 넣기** — 지금 CI가 도는 것은 `test_b66_generic_archive_bounds.py`뿐이다. `test_b66_generic_compile.py`(합성 양식 전 구간: analyze→compile→render→certify→mutations→literal_scan, 로컬 3 passed / 약 10초, PyMuPDF 필요)는 어느 워크플로도 실행하지 않는다. 현재 보증은 "기록된 증거"이지 "계속 도는 검사"가 아니다.
4. **2번째 양식 계정 여정** — 별도 승인·별도 큰 작업. 이 대조표 범위 밖.

## 6. 결론 플래그

```text
#3595_ACCEPTANCE_MATRIX = THIS_DOCUMENT
ANALYSIS_AND_REPRODUCTION_SEPARATE = YES
REPRODUCTION_BEFORE_EXECUTION = YES
REFERENCE_PDF_ORACLE_REQUIRED = YES
CERTIFICATION_STATE_PERSISTED = PARTIAL
UNCERTIFIED_NEW_TEMPLATE_EXECUTION = DENIED
SOURCE_REANALYSIS_PER_REPEAT = 0
SECOND_TEMPLATE_CERTIFIED_BENCHMARK = YES
SECOND_TEMPLATE_ACCOUNT_JOURNEY = NOT_DONE
CRITICAL_GATES_INDEPENDENT = PARTIAL
CERTIFIED_WITH_TOLERANCE = NOT_IMPLEMENTED
PIPELINE_TEST_IN_CI = NO
SILENT_APPROXIMATION_ACCEPTANCE = NO
ISSUE_3595_CLOSE = NO
```
