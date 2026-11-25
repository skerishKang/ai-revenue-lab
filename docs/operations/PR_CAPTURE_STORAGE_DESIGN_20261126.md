# PR 캡처 저장소 밖 설계

- 날짜: 2026-11-26
- 기준 저장소: `skerishKang/ai-revenue-lab`
- 기준 SHA: `ae63d8f25f5d6d9a0a252fc934173ca1f971027d`
- 범위: 설계, 업로드 도구, 회귀 시험
- 비목표: 기존 PNG 삭제, Git 히스토리 재작성, 신규 비공개 저장소 생성, 운영 배포

## 1. 실측

`padiem-reports/`의 현재 트리는 `git ls-tree -rl`로 측정했다. 최근 30일 증가량은
2026-10-27 00:00 KST 이후 2026-11-27 00:00 KST 이전 커밋에서 새로 도입된 blob의
크기를 합한 값이다. 동일 blob은 한 번만 센다.

| 항목 | 파일 수 | 크기 |
|---|---:|---:|
| 현재 `padiem-reports/` 전체 | 2,393 | 487,885,937 bytes (465.28 MiB) |
| 현재 PNG/JPG/JPEG/WEBP | 1,868 | 483,421,943 bytes (461.03 MiB) |
| 현재 JSON | 452 | 4,185,178 bytes (3.99 MiB) |
| 최근 30일 신규 blob 전체 | 1,862 | 368,953,069 bytes (351.86 MiB) |
| 최근 30일 신규 이미지 blob | 1,407 | 363,555,160 bytes (346.71 MiB) |

이미지가 현재 바이트의 99.1%를 차지한다. 새 클론의 Git pack은 643.99 MiB였다.
`padiem-reports/`의 현재 크기와 pack 크기는 서로 다른 측정 대상이며, pack에는 다른
저장소 파일과 히스토리 압축이 포함된다.

## 2. 대안 비교

| 대안 | 비용 | 보관 | CTO가 PR에서 바로 보는 방식 | 공개 저장소 노출 |
|---|---|---|---|---|
| GitHub Actions artifact | Public 저장소 실행은 무료. artifact 저장은 Packages와 할당량을 공유하고 초과 사용량은 과금된다. | Public 최대 90일, 기본 90일. Private 최대 400일. | PR 본문의 실행 링크에서 다운로드. 이미지가 본문에 인라인으로 표시되지는 않는다. | Public 저장소의 읽기 권한을 가진 사람이 artifact를 받을 수 있어 민감한 캡처의 비공개 보관에 부적합하다. |
| PR 댓글 첨부 | GitHub 저장 공간을 사용한다. 자동화를 위한 공개 REST binary 업로드 계약은 문서화되어 있지 않다. | 사용자가 보관 기간을 정하지 못한다. | 댓글에 인라인으로 가장 직접적이다. | Public PR이면 첨부도 공개된다. 브라우저 수동 첨부에 가까워 CI 자동화가 약하다. |
| 별도 비공개 저장소 (`*-sc`) | 별도 private 저장소와 접근 권한 운영이 필요하다. Actions 시간, artifact 저장, LFS 대역폭 과금은 쓰지 않는다. | 저장소를 삭제하거나 히스토리를 고치기 전까지 유지된다. | PR 본문의 비공개 blob 링크를 클릭한다. 권한 없는 공개 방문자는 404을 본다. | PNG 바이트는 비공개 저장소에만 있다. Public PR에는 저장소 이름과 링크만 노출된다. |
| Git LFS | Free/Pro/Free for organizations는 저장·대역폭 각각 10 GiB, Team/Enterprise는 각각 250 GiB. 초과 시 과금 또는 차단된다. | LFS 객체와 포인터가 남는 한 유지된다. | Public 저장소의 파일 링크로 이동한다. | Main 저장소가 public이면 LFS 객체도 공개 읽기 범위다. 기존 PNG을 LFS로 옮기려면 히스토리 재작성이 필요하다. |

## 3. 추천: 비공개 캡처 컴패니언

`skerishKang/ai-revenue-lab-sc`를 비공개 컴패니언 저장소로 쓰는 방안을 추천한다.
이름은 기존 `lovetree-sc`, `cgi-sc` 관례를 따른다. 저장소는 CTO가 private로 생성하고
README로 초기화한다. 이번 작업은 저장소를 만들지 않는다.

선택 이유:

1. PR 본문에서 한 번 클릭해 영구 링크로 캡처를 볼 수 있다.
2. artifact 만료 기간에 증거가 사라지지 않는다.
3. PNG는 public 코드 저장소에 추가되지 않아 새 커밋의 clone/checkout 증가를 막는다.
4. JSON 요약은 기존 public 저장소에 남아 diff와 자동 검증이 가능하다.
5. `gh` 인증만으로 자동화할 수 있고 별도 토큰을 코드나 환경에 넣지 않는다.

이 저장소도 캡처가 계속 쌓이면 커지므로 보관 주기는 대표가 별도로 정한다. 이번
1단계에서는 기존 이력 보존을 전제로 하므로 삭제 주기를 만들지 않는다.

## 4. 도구 계약

도구: `tools/publish_pr_captures.py`

```bash
python tools/publish_pr_captures.py \
  --pr 9001 \
  --head-sha "$(git rev-parse HEAD)" \
  --summary padiem-reports/2026-11-26/7811-example/manifest.json \
  --capture padiem-reports/2026-11-26/7811-example/capture-0.png \
  --capture padiem-reports/2026-11-26/7811-example/capture-1.png \
  --private-repo skerishKang/ai-revenue-lab-sc
```

- JSON 요약은 exact HEAD에 추적되어 있고 작업 트리의 바이트도 같아야 한다. 도구는 JSON을 업로드하지 않는다.
- 캡처는 1장 이상 8장 이하만 받는다. #8661의 기존 8장 제한을 약화하지 않는다.
- PR 본문에 이미 캡처 블록이 있으면 같은 경로 묶음만 다시 실행할 수 있다. 다른 묶음을 추가해 PR당 8장을 넘기지 못한다.
- 캡처는 요약과 같은 `padiem-reports/<날짜>/<묶음>/`에 있어야 하며 실제 이미지
  시그니처를 검사한다.
- 대상 저장소가 private이고 초기화되어 있어야 한다. Public 저장소에는 업로드하지 않는다.
- 비공개 경로는 public 저장소의 상대 경로를 그대로 쓰고 blob SHA로 immutable 링크를 만든다. 같은 경로에 다른 바이트가 있으면 덮어쓰지 않고 거부한다.
- PR의 current head가 `--head-sha`와 같을 때만 업로드하고, 본문 갱신 직전에도 다시 검사한다.
- PR 본문의 `<!-- padiem-captures:start -->` … `<!-- padiem-captures:end -->` 블록만
  교체한다. 같은 입력을 다시 실행해도 블록이 중복되지 않는다.
- `.gitignore`는 대소문자를 가리지 않고 새 `padiem-reports` 이미지를 무시한다. 이미 추적된 PNG는 그대로 남는다.

## 5. 기존 증거 규칙과의 정합

- #7811의 픽셀 비교, 제어쌍, 변조, 수치 전후, JSON 요약 요구는 변경하지 않는다.
- #8661의 최대 8장은 도구 입력과 기존 PR guard 양쪽에서 유지한다.
- 캡처 링크는 PR 본문에 남기므로 CTO가 별도 보고서를 찾지 않고 증거로 이동할 수 있다.
- artifact는 만료가 허용되는 CI 임시 산출물에만 사용한다.

## 6. 대표 결정이 필요한 후속

- 기존에 커밋된 PNG 삭제 여부
- Git 히스토리 재작성 및 강제 푸시 여부
- 비공개 컴패니언 저장소 생성과 보관 주기

세 항목 모두 이번 PR에서 실행하지 않는다.
