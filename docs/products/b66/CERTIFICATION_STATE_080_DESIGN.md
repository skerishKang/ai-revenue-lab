# 인증 상태 영속 설계 (080 초안, #3595 후속)

```text
DOC_STATUS = DESIGN_ONLY
MIGRATION = docs/products/b66/drafts/080_b66_template_source_certification_state.sql (미적용)
APPLIED_IN_MIGRATIONS_DIR = NO
PRODUCTION_MUTATION = NO
DEPLOY = NO
MERGE = CTO_CONFIRMATION_REQUIRED
```

## 1. 지금 무엇이 없는가

`#3595`가 요구하는 다섯 상태(`ANALYZED` / `REPRODUCTION_IN_PROGRESS` / `CERTIFIED` / `CERTIFIED_WITH_TOLERANCE` / `REJECTED`)와 허용 오차 기록은 어디에도 남지 않는다.

| 위치 | 지금 | 문제 |
| --- | --- | --- |
| `b66_template_source.status` | `CHECK (status IN ('uploaded','disabled'))` (migration 060) | 업로드/비활성만 표현한다. 분석·재현·인증 단계가 없다. |
| 승인 번들 manifest | `certification.status == "PASS"` 단일 비트 (`b66_certified_quote_bundle.parse_bundle`) | 이진 통과만 있다. `CERTIFIED_WITH_TOLERANCE`와 그 근거를 담을 자리가 없다. |
| 도구 증거(`tools/b66_generic/evidence/*.json`) | 저장소 파일 | 계정/템플릿 행과 연결되지 않는다. |

결과: "이 고객 양식이 어느 단계까지 갔는가"를 코드가 답할 수 없고, 오차를 허용했다면 **왜·누가·무엇을** 허용했는지도 남길 수 없다.

## 2. 어디에 저장하는가

**기존 `b66_template_source` 행을 넓힌다.** 새 표를 만들지 않고, 컬럼만 더한다.

이유:

- 업로드 1건 = 양식 1건 = 인증 1건이라 1:1이면 충분하다(같은 원본의 재인증은 같은 행을 갱신).
- 새 표는 조인·권한·정리 규칙을 하나 더 만들고, 이번 요구는 "상태가 남는가"지 "이력이 쌓이는가"가 아니다.
- `migrations/`의 기존 규율(테이블 재빌드 금지)과 맞다. 060도 재빌드를 했지만 그건 소진된 예외이고, 080은 ADD COLUMN만 쓴다.

이력(모든 전이 로그)이 필요해지는 시점은 별도 판단이다 — 그때 별도 표(append-only)로 간다. 이 초안은 그 결정을 앞당기지 않는다.

## 3. 컬럼 (초안 SQL 그대로)

```sql
ALTER TABLE b66_template_source ADD COLUMN certification_state TEXT
    CHECK (certification_state IS NULL OR certification_state IN (
        'ANALYZED','REPRODUCTION_IN_PROGRESS','CERTIFIED',
        'CERTIFIED_WITH_TOLERANCE','REJECTED'));
ALTER TABLE b66_template_source ADD COLUMN certification_evidence_json TEXT
    CHECK (certification_evidence_json IS NULL OR length(...) <= 8192);
ALTER TABLE b66_template_source ADD COLUMN certification_updated_at TEXT;
```

- `certification_state IS NULL` = **인증 기록 없음**. 기본값을 `ANALYZED`로 두지 않는 이유: 한 번도 분석하지 않은 업로드 행이 "분석됨"으로 보이면 안 된다. NULL은 통과가 아니다.
- `certification_evidence_json`은 8 KiB 상한. 게이트 결과·측정 델타·허용 오차 기록만 담고, **고객 원본 바이트나 개인정보는 담지 않는다**(원본은 #3884 custody, 이 컬럼은 판정 근거만).
- `certification_updated_at`은 마지막 전이 시각(ISO-8601, 서버가 쓴다).

## 4. 전이 규칙 (다음 슬라이스가 구현할 계약)

```text
NULL -> ANALYZED                     분석 결과가 저장될 때
ANALYZED -> REPRODUCTION_IN_PROGRESS 재현/비교가 시작될 때
REPRODUCTION_IN_PROGRESS -> CERTIFIED | CERTIFIED_WITH_TOLERANCE | REJECTED
CERTIFIED | CERTIFIED_WITH_TOLERANCE -> REPRODUCTION_IN_PROGRESS
                                     렌더러/지오메트리/폰트/자산/표 구조/줄바꿈이
                                     바뀌어 인증 적용 범위를 재검토할 때
REJECTED -> ANALYZED                 원본이 바뀌었거나 다시 분석할 때만
```

- `CERTIFIED_WITH_TOLERANCE`는 `accepted_differences`가 비어 있으면 쓸 수 없다(fail closed).
- `REJECTED`에서 반복 출력은 거절된다. 이는 오늘의 번들 거절을 약화시키지 않는다 — 오히려 그 앞단에 사유를 남긴다.

허용 오차 기록(예시 형태, 이 초안은 스키마를 강제하지 않고 상한만 둔다):

```json
{
  "accepted_differences": [
    {"area": "text_spacing", "severity": "minor", "reviewed_by": "<owner id>", "reviewed_at": "<ISO-8601>"},
    {"area": "logo_position", "measured_delta_pt": 1.5, "reviewed_by": "<owner id>", "reviewed_at": "<ISO-8601>"}
  ],
  "reference_pdf_sha256": "<64 hex>",
  "gates": {"TABLE_LINES_BORDERS": true, "ASSET_LAYERING": true},
  "raster": {"72dpi": 0, "150dpi": 0, "300dpi": 0}
}
```

에이전트가 스스로 `accepted_differences`를 채우는 경로는 만들지 않는다. 리뷰한 사람과 시각이 없으면 그 기록은 무효다.

## 5. 번들 manifest는 건드리지 않는다

`parse_bundle`은 manifest 키 집합이 정확히 일치해야 통과한다(`_MANIFEST_KEYS`). 필드를 하나 더하면 **이미 발급된 승인 번들이 전부 거절**된다. 그래서 상태는 D1 행에 남기고, 번들은 지금 그대로 `certification.status == "PASS"`만 요구한다. 두 저장소가 어긋날 때는 **번들이 이긴다**(실행 경로가 번들을 읽으므로) — D1 상태는 판정·감사 기록이고 실행 권한을 새로 만들지 않는다.

이 분리를 명시하는 이유: 상태 컬럼이 생겼다고 해서 "CERTIFIED 행이면 번들 없이도 렌더"가 되면 안 된다.

## 6. 이 슬라이스에 없는 것

- 라우트/스토어 코드 없음(전이를 쓰는 API는 다음 슬라이스).
- `migrations/`로 이동하지 않음 — 지금 옮기면 다음 Chat 배포가 D1 게이트에서 이 파일을 집어 갈 수 있다. CTO가 배포 순서를 정할 때 옮긴다.
- D1 게이트 실행·배포·머지 없음.

## 7. 적용 순서 (CTO 결정 대기)

```text
1. 이 설계 + 초안 PR 리뷰 (코드 변경 0)
2. 초안을 apps/padiem-chat/migrations/080_*.sql 로 이동하는 PR
3. D1 게이트로 080 적용 (아스트라2 배포 창구와 같은 순서 규율: main 일치 → 게이트 → 배포)
4. 전이를 쓰는 최소 API/스토어 PR (그때 상태 전이 테스트 포함)
```

## 8. 검증 (이 PR에서 실제로 돌린 것)

- 초안 SQL을 SQLite 인메모리에 migration 060 형태의 `b66_template_source`와 함께 적용: 3개 `ADD COLUMN` 모두 성공, 기존 행의 상태는 `NULL` 유지.
- `certification_state='NOPE'` UPDATE는 CHECK로 거부, `'CERTIFIED'`는 허용.
- 초안 파일에 `DROP`/`CREATE`/`RENAME`/`UPDATE`/`DELETE`가 없음(테스트로 고정).
