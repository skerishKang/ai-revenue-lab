# #5972 웹폰트 자체 호스팅 구현 (B안 확정)

STATUS=TYPOGRAPHY_IMPLEMENTED_LOCALLY
ISSUE=#5972 · PR=#5979
BASE COMMIT=`d963d3667257686cea5ade0f2221d6cffe89de9c`
DECISION=**B안** — 마루부리 제목 + Pretendard 본문 (CENTRAL CTO 승인)

앞선 A/B 분석(`TYPOGRAPHY.md`)에서 확인된 근본 원인은 **`@font-face` 선언 0건**이었습니다.
이번 작업은 그 원인을 없애고, 두 서체를 **자체 호스팅**으로 확정 적용한 구현 기록입니다.

---

## 1. 원인 (실측)

구현 전 운영 중이던 V2 미리보기(HEAD `1de2abc39`)를 실브라우저로 측정한 결과:

| 측정 | 값 |
|---|---|
| `document.fonts.size` | **0** (등록된 웹폰트 없음) |
| 폰트 파일 네트워크 요청 | **0건** |
| 제목 실제 렌더 서체 | **Batang** (방문자 PC 설치 글꼴) |
| 본문 실제 렌더 서체 | **Noto Sans KR** (방문자 PC 설치 글꼴) |

CSS에는 `--font`/`--font-serif` 이름만 있었고 로딩이 없었습니다. 즉 서체가 방문자 환경에 따라
달라지는 상태였으며, 숫자·라틴은 Times 계열로 섞여 렌더되고 있었습니다.

측정 방법: Chromium CDP `CSS.getPlatformFontsForNode`(브라우저가 보고한 **실제 사용 서체**).
`document.fonts.check()`는 미등록 서체에도 `true`를 반환해 증거로 쓸 수 없습니다.

---

## 2. 폰트 확보와 라이선스

| 서체 | 배포처 | 버전 | 파일 | 용량 |
|---|---|---|---|---|
| Pretendard Variable | `cdn.jsdelivr.net/npm/pretendard@1.3.9` (repo `orioncactus/pretendard`) | 1.3.9 고정 | `woff2-dynamic-subset` 92개 | 2,957,724 B |
| MaruBuri Bold | `hangeul.pstatic.net` (NAVER 한글한글 아름답게) | 현행 | 1개 | 451,596 B |

- 둘 다 **SIL Open Font License 1.1** — 상업적 이용·번들·재배포 허용 (파일 자체 판매만 금지).
- 원본 파일 **무변형** 사용. 서브셋·리네이밍·리패킹 없음.
- 라이선스 고지 동봉: `static/fonts/LICENSE-Pretendard.txt`, `static/fonts/LICENSE-MaruBuri.txt`,
  출처·재배포 절차: `static/fonts/README.md`.
- 합계 추가 용량 **3,409,320 B** (93개 파일, 최대 단일 파일 43,920 B).

## 3. 적용

`static/fonts/maruburi.css` (마루부리 Bold) + `static/fonts/pretendard/pretendard-variable-dynamic-subset.css`
(공식 CSS 원문, 상대경로 그대로 동작) 를 **5개 페이지 모두**에서 `styles.css` 앞에 연결했습니다.

```html
<link rel="stylesheet" href="./static/fonts/maruburi.css" />
<link rel="stylesheet" href="./static/fonts/pretendard/pretendard-variable-dynamic-subset.css" />
<link rel="stylesheet" href="./static/styles.css" />
```

토큰 교체 (`styles.css`):

```css
--font: "Pretendard Variable", "Pretendard", "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif;
--font-serif: "MaruBuri", "Noto Serif KR", "Nanum Myeongjo", serif;
```

웹폰트 패밀리를 스택 맨 앞에 두어 **로컬 설치 글꼴이 렌더를 가로채지 못하게** 했습니다.

### 서체 배분

| 마루부리 Bold | Pretendard |
|---|---|
| 히어로 헤드라인, 섹션 제목(`.section-title`), 남색 밴드 제목, 소식 제목, 요약 카드 수치, 브랜드 모노그램 | 본문·리드, 상단 메뉴, 버튼, 카드 제목·날짜·설명, 칼럼/타일 제목, 표, 바닥글 |

카드·버튼·메뉴는 지시대로 전부 Pretendard입니다. 요약 카드의 큰 수치(`5건`)와 브랜드 모노그램은
기존 디자인에서 이미 세리프 계열이던 표시 요소라 그대로 유지했습니다(구도 보존).

---

## 4. 검증 — 브라우저 실제 로딩

`fontcheck.js` (Playwright + CDP), 5개 페이지 × 2 뷰포트 = 10회 로드, 원시 로그는
`font-network-after.json` / `font-network-before.json`.

| 항목 | 구현 전 | 구현 후 |
|---|---|---|
| 등록된 `@font-face` | 0 | **93** |
| 폰트 파일 요청 | 0 | 페이지당 **9~12건, 전부 자사 경로 200** |
| 외부 폰트 호스트 요청 | 0 | **0** (`hangeul.pstatic.net`·jsdelivr 등 0건) |
| 실제 렌더 서체 | Batang / Noto Sans KR | **MaruBuri / Pretendard Variable** |
| 로컬 설치 글꼴 의존 | 있음 | **없음** |

- 10회 로드 전부 `failures: []`.
- 5개 페이지에서 사용된 서로 다른 폰트 파일은 총 13개(프리텐다드 서브셋 12 + 마루부리 1).
- `@font-face` 93개 = 프리텐다드 서브셋 92 + 마루부리 1.

## 5. 검증 — 레이아웃 (원본 구도 보존)

| 지표 | 구현 전 | 구현 후 (1440×900) | 구현 후 (390×844) |
|---|---|---|---|
| 히어로 높이 | 361.4px | **361.4px** (동일) | 430.8px (동일) |
| 문서 높이 | 1478px | **1478px** (동일) | 3455px (동일) |
| 카드 높이 | 249.1 ×4 | **249.1 ×4** (동일) | 267.5 / 247.9 / 247.9 / 171.3 (동일) |
| 제목 줄 수 | 2줄 | **2줄** | **2줄** |
| 제목 글리프 폭 | 504.5 / 435.4px | 475.9 / 412.1px | 247.9 / 214.7px |
| 가로 오버플로 | 없음 | **없음** | **없음** |

- 히어로·카드·스트립 높이가 소수점까지 동일 → 구도와 여백 리듬은 그대로입니다.
- 제목은 MaruBuri에서 5.3~5.7% 좁아졌고 줄 수는 2줄 유지(히어로 컬럼 620px, 여유 확보).
- 내부 페이지 문서 높이는 ±20px 이내 변동(줄바꿈 지점 변화). 예: media 모바일 6885→6865px.
- 파란색 강조 체계(`#004884` / `#00609c`)와 카드·통계 밴드 구조는 변경 없음.

## 6. 비용

index.html 콜드 로드 전송량(실측, `transferSize` 합):

| | 구현 전 | 구현 후 |
|---|---|---|
| 합계 | 12,267 B | 842,694 B |
| 폰트 | 0 B | 741,616 B (프리텐다드 서브셋 ≈290 KB + 마루부리 451.6 KB) |

프리텐다드는 공식 `unicode-range` 동적 서브셋이라 페이지에 실제로 쓰인 조각만 내려받습니다.
마루부리 Bold는 공식 배포에 서브셋 빌드가 없어 한글 전체(451.6 KB)가 단일 파일로 내려갑니다 —
B안의 알려진 비용이며 사전 A/B 분석(721 KB)과 일치합니다.

## 7. 캡처

| 파일 | 내용 |
|---|---|
| `impl-before-after-1440.jpg` | 1440×900 히어로 좌:구현 전 / 우:구현 후 |
| `impl-before-after-390.jpg` | 390×844 동일 비교 |
| `impl-after-hero-1440.jpg`, `impl-after-hero-390.jpg` | 구현 후 히어로 확대 |
| `impl-pages-1440.jpg`, `impl-pages-390.jpg` | 5개 페이지(홈·소개·활동·정책·미디어) 적용 결과 |

---

## 8. 원본 시안 PNG 노출 점검 (커밋 `fb8dd1041`)

**결론: 공개 저장소에서 현재도 내려받을 수 있습니다.** 저장소는 PUBLIC입니다.

| 항목 | 값 |
|---|---|
| 경로 (fb8dd1041이 추가) | `apps/councillor-prototype/docs/analysis-5972/reference-1440x900.png` |
| 크기 / 해상도 / blob | 1,597,002 B / 1440×900 / `1b60d0aaf0b1ef277d48085a499cdfbc4bc7a2bf` |
| 현재 HEAD 포함 여부 | **없음** (이후 커밋에서 삭제됨) |
| 공개 접근 | `raw.githubusercontent.com/.../fb8dd1041/<경로>` → **HTTP 200**, GitHub blob 페이지 → **200** |

같은 커밋이 추가한, 시안을 포함한 다른 이미지도 HEAD에서는 빠졌지만 이력에는 남아 있습니다:
`cmp-1440x900.png`(3,020,568 B), `cmp-390x844.png`(451,009 B),
`phase3/reference-top-1440x900.jpg`(289,771 B), `phase3/cmp-reference-vs-after-1440.jpg`(446,595 B).

또한 **원본 시안 자체가 현재 브랜치 HEAD에 추적 중**입니다(커밋 `ec74a3c0e`가 추가, `main`에는 없음):
`reference/issue-5972-councillor-v2/reference_01..04*.png` 합계 약 8.2 MB.
`git check-ignore` 결과 무시 대상이 아니며, `raw.githubusercontent.com`에서 200으로 내려받힙니다.

### 정리 방법과 영향 (실행하지 않음 — 별도 승인 필요)

1. **전진 삭제(안전, 이력 재작성 없음)** — 해당 경로를 현재 HEAD에서 일반 커밋으로 삭제.
   영향: 앞으로의 체크아웃·복제·PR "Files changed"에서 사라짐. 단 **과거 커밋 SHA로는 계속 접근 가능**
   (GitHub은 참조 가능한 커밋의 blob을 유지). 즉 노출 차단 효과는 없습니다.
2. **이력 재작성(실효적, 조율 필수)** — 미러에서 `git filter-repo --path <경로> --invert-paths` 후
   브랜치 force-push. 영향: 이 브랜치의 **모든 커밋 SHA가 바뀌고**, PR #5979는 재생성/재지정이 필요하며,
   다른 작업자의 클론은 재클론해야 하고 SHA를 참조하는 문서·자동화가 깨집니다. 지시대로 실행하지 않았습니다.
3. **GitHub 측 제거 요청** — 재작성 후에도 GitHub Support 요청 없이는 CDN 캐시·포크 사본이 남습니다.
   2번과 3번을 함께 해야 실질적 차단이 됩니다.
4. **재발 방지** — `reference/issue-*/`를 `.gitignore` 대상으로 두고 시안은 저장소 밖(비공개 보관소)에
   두며, 시안류 파일이 커밋되면 실패하는 CI 가드를 추가합니다.

---

## 9. 이번 커밋이 하지 않은 일

- **미리보기 배포만** 수행. 운영 의원 홈페이지(`apps/padiem-chat/static/councillor/`)는 변경하지 않았습니다.
- 머지하지 않았습니다(`MERGED=NO`).
- 이력 재작성·force-push를 하지 않았습니다.
- 기존 기능·문구·데이터·색상·구도를 변경하지 않았습니다.
