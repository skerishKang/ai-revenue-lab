# Chat 객체 원복 계획 — D1 전환 ③-2 (2026-10-31)

계획(#6354) ③은 D1뿐 아니라 **객체 저장소(로컬 객체 + R2 + 파일 레인 원본) 참조 일관성**을 전환 완료 기준으로 두고, 되돌리기를 "#6197 (가) 핸드백 + D1 게이트 apply/verify + **객체 복원**"으로 적었습니다. 이 문서는 그 "객체 복원"이 실제로 무엇인지 정하고, 필요한 도구만 만들었습니다.

## 1. 객체 위치 표

| 객체 종류 | 현재 위치 | 전환 후 위치 | 전환 중 새로 생기는 객체 | 되돌릴 때 |
| --- | --- | --- | --- | --- |
| workspace·Claw 문서 바이너리 | R2 `padiem-workspace-files`, metadata는 Chat D1 `object_key` 열(`claw_document_metadata` 등) | COM2 `LocalDiskR2(data_dir/objects)` + metadata COM2 SQLite | 쓰기 정지 창에서는 0 (업로드가 POST/PUT → 503) | R2를 건드리지 않으므로 되돌릴 것 없음. 창 밖 생성분만 R2로 올린 뒤 핸드백 |
| B66 견적 자산·템플릿 원본 | 같은 R2 버킷, metadata D1 `object_key`(`b66_quote_asset`, `b66_template_source`) | COM2 로컬 객체 + COM2 SQLite | 같음 | 같음 |
| 전체 문맥 원본(full context originals) | R2 (`D1HistoryStore(full_context_bucket=r2)`) | COM2 `LocalDiskR2(data_dir/objects)` | 같음 | 같음 |
| 프로젝트 파일(텍스트) | D1 전용, 객체 없음 | COM2 SQLite | D1 행이므로 핸드백에 포함 | 행 단위 핸드백 |
| 파일 레인 첨부(#5881·#6321) | COM2 HDD `/mnt/d/padiem/file-lane`, HTTP 8788 | 그대로 COM2 | COM2에만 생김 | 컴2 정본이므로 그대로 둠 |
| COM2 오프사이트 백업(#5093·#6287) | COM2 → R2 업로드(방향 반대) | 그대로 | 백업 세대 추가 | 되돌림과 무관 |

## 2. 왜 대부분 되돌릴 필요가 없는가

- **삭제는 상대 저장소에 전파되지 않습니다.** COM2에서 문서를 지워도 R2 사본은 남고, 반대도 같습니다. 전환 후 COM2 쪽 코드가 지운 객체의 R2 사본은 그대로 있으므로 복원할 대상이 없습니다.
- **덮어쓰기가 없습니다.** `scripts/ops/r2_sync.py`는 활성 게대(generation)를 기준으로 새·변경 객체만 복사해 **새 불변 세대**를 만들고 기존 세대를 덮어쓰지 않습니다. 원격에서 지워진 객체도 기록만 하고 제거하지 않습니다.
- 그래서 되돌림에 필요한 동작은 "되돌리기"가 아니라 **"덮기"**입니다. 창 밖(④ 이후 쓰기 재개 뒤)에 COM2가 만든 객체를 R2에 올려, D1로 되돌아가는 행이 참조하는 객체가 실제로 존재하게 만드는 것입니다.

## 3. 도구 필요 여부 판단

| 필요 | 도구 | 근거 |
| --- | --- | --- |
| 필요 | `.github/scripts/chat_object_reference_check.py` (이 PR, 작게 만듦) | 핸드백이 되돌리는 행이 참조하는 `object_key`가 미러에 없으면 되돌림 뒤 첨부가 깨집니다. 이 실패는 D1 패리티가 잡지 못합니다 |
| 불필요 | 객체 undo·삭제 되돌림 도구 | §2 — 상대 저장소를 지우지 않고 덮어쓰지도 않으므로 되돌릴 상태가 없습니다 |
| 재사용 | `scripts/ops/r2_sync.py`(불변 세대 미러), `wrangler r2 object` 업로드 | 미러 방향 전송은 이미 있는 도구를 씁니다. 새 전송 도구를 만들지 않았습니다 |

`chat_object_reference_check.py` 동작:
- D1 사본(SQLite)에서 이름이 객체 키인 열(`object_key`, `r2_key`, `context_key`, `full_context_key` 등)을 찾아 참조 키를 모읍니다. 열 이름 기반이라 표 목록을 하드코딩하지 않습니다.
- 미러 목록(`r2_sync` 매니페스트, 또는 `{"keys": [...]}`·`{"objects": [...]}`)과 대조합니다.
- `mode=ro`로만 열고, **키 값을 출력하지 않습니다.** JSON 리포트에는 건수와 누락 집합 다이제스트만 담고, 키 값을 쓰려면 `--include-keys`를 명시해야 합니다(로컬 운영자용).
- 종료 코드: 일치 0 / 누락 1 / 입력·설정 문제 2. `plan`/`verify`와 같은 "읽기 전용·승인 비교" 규율입니다.

## 4. 리허설 단계 반영

`CHAT_D1_CUTOVER_WRITE_FREEZE_AND_REHEARSAL_20261031.md`의 절차에 **4b 객체 참조** 단계를 넣습니다.

```
python .github/scripts/chat_object_reference_check.py \
  --db d1-after.sqlite3 --inventory r2-inventory.json --json object-reference.json
```

| 항목 | 값 |
| --- | --- |
| 소요 목표 | 3분 |
| 판정 | `CHAT_OBJECT_REFERENCE=MATCH`, 종료 코드 0 |
| 실패 시 | 누락 키를 R2로 올린 뒤(mirror) 다시 4b. 해결되지 않으면 6번(핸드백)으로 진행하지 않고 CTO 보고 |
| 6번 뒤 | 핸드백 적용 후 같은 명령을 한 번 더 돌려 되돌림 뒤에도 참조가 살아 있음을 확인 |

## 5. 쓰기 정지 창에서 객체가 새로 생기지 않는 이유

업로드 경로는 전부 쓰기 메서드입니다: 프로젝트 파일 생성·첨부 업로드·B66 자산 업로드가 `POST`/`PUT`이고, `#6363`의 쓰기 정지는 이들을 `503`으로 막습니다. 아스트라5의 늦은 쓰기 분류표가 읽기 메서드로 객체를 만드는 경로를 찾으면 `PADIEM_CHAT_WRITE_FREEZE_PATHS`에 추가하면 됩니다.

## 6. 테스트

`.github/tests/test_chat_object_reference_check.py`

- 모든 참조 키가 미러에 있으면 MATCH·종료 코드 0, 표별 건수 출력.
- 미러에 없는 키 1건 → GAP·종료 코드 1, 누락 다이제스트 계산.
- `project_file_key`처럼 키가 아닌 열은 스캔하지 않음.
- 미러 목록 형식 4종(리스트·`keys`·`objects` 사전·`objects` 문자열) 허용, 형식 불명·빈 목록은 거부.
- 키 열이 없는 DB는 거부(종료 코드 2).
- 입력 파일 부재 → 종료 코드 2.
- DB·미러 파일 SHA-256 불변(읽기 전용), JSON 리포트에 키 값 미포함, `--include-keys`일 때만 포함.

## 7. 이 문서가 주장하지 않는 것

- 실제 R2 목록과 COM2 저장소를 조회하지 않았습니다. 검증은 합성 DB와 합성 미러 목록으로만 했습니다.
- 창 밖(④ 이후) 생성 객체의 실제 규모를 측정하지 않았습니다.
