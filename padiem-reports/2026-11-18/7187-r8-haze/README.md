# #7187 8차 — 흰 안개(.78) 쓰임새 토큰 (검증 기록)

## 묶음

- 값: `rgba(255, 255, 255, .78)` — 12선언 · 11파일 (사이드바 시트,
  `padiem-glass.css`, `var()` fallback 내부, `history.css` auth 제외 후).
- 치환: **11선언**. 제외: `styles.css:170` 1선언(바이트 고정 참조 미러).
- 선택 이유: 감사 조건(10~20선언)에 맞는 최종 후보. `.07`은 죽은 선언 1개
  (`surfaces` `.composer`)로 9선언, `.10`은 9선언, `.92`는 기존 토큰 중복,
  `.14`는 실측에서 최대 8선언만 칠해짐. `.78`은 computed 실측으로 살아
  있음을 확인한 10선언 이상인 묶음이며, 실측 불가 3선언
  (`.conversation-jump` 숨음 버튼, reading 모드, 인용 블록)은 `!important`
  덮어쓰기가 없는 정적 live문이다. `.assistant-meta`는 상태별 승자를 확인해
  `surfaces` 선언도 포함했다(home 상태 표면값, chat·claw 상태 editorial값).

## 토큰

삽입 위치: `apps/padiem-chat/static/padiem-tokens.css:145-153` (`:root`).
테마 블록에서는 덮지 않는다(5테마 모두 동일값).

| 토큰 | 값 | light | dark | glass | cinematic | home | 쓰임새 |
|---|---|---|---|---|---|---|---|
| --surface-veil-haze | .78 | 동일 | 동일 | 동일 | 동일 | 동일 | 배경 3 |
| --line-veil-haze | .78 | 동일 | 동일 | 동일 | 동일 | 동일 | 테두리 4 |
| --text-veil-haze | .78 | 동일 | 동일 | 동일 | 동일 | 동일 | 글자 4 |

## 기준선

- before (`503255544`): `css_color_literals` **1,906** ·
  `css_color_literals_unthemed` **1,215**
- after: **1,896** · **1,211** (−10 / −4)
- `structure_baseline.json`은 숫자 두 줄만 변경
  (`git diff origin/main --stat` = 2 insertions / 2 deletions).

## 픽셀 비교 (before=`origin/main`, after=작업 트리)

5테마 × 2뷰포트 × 5화면 = **50조합, 허용 잔차 8px 기준 전 조합 무차이**.

| 화면 | 조합 | 결과 |
| --- | --- | --- |
| home-logout | 10 | 0 |
| conversation | 10 | 0 |
| settings-dialog | 10 | 0 |
| feedback-dialog | 10 | 0 |
| util | 10 | 0 |

작업 트리 로컬 산출물: `E:\chat-qa\7810\261116\compare_report.json`.

## 변조 시험

새 토큰 2개를 `rgba(255, 255, 255, .78)` → `rgba(255, 0, 0, 0.9)`로
바꾼 사본을 서빙해 비교했다.

| 항목 | clean | tampered |
| --- | --- | --- |
| `.sidebar` background (surface, padiem-home) 첫 정지 | `rgba(255, 255, 255, 0.78)` | `rgba(255, 0, 0, 0.9)`(둘째 정지 `.58` 그대로) |
| `.assistant-meta` color (text, cinematic) | `rgba(255, 255, 255, 0.78)` | `rgba(255, 0, 0, 0.9)` |
| `.sidebar` border-right / body 배경 (제어쌍) | 그대로 | 그대로 |
| home-logout(padiem-home) 픽셀 | — | 237,933px 차이 |
| conversation(cinematic) 픽셀 | — | 722px 차이 |
