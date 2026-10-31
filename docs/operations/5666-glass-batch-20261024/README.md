# 5666-glass-batch-20261024 — #5672·#5673·#5666 일괄 검증 증거

CENTRAL 통합 지시(#5666 댓글, 2026-10-24)에 따른 1회 LOCAL 작업의 근거 자료.
대상: `chat.padiem.net` 실운영 (서빙 CSS = origin/main `f3e93b6d5` 이후, library.css/meeting-capture.css diff 일치 확인).

## #5672 Meeting 820×1180 — 결함 없음 (코드 변경 없음)

- `5672-meeting-820x1180-production.png`: 실운영 캡처 (로그인 세션, padiem-glass).
- 계측: `.meeting-view` background `rgb(242,245,247)`(불투명, #5676 수정 활성), `position: relative; z-index: 2`(#5691 수정 활성) > 배경 포트레이트 `body::before` `position: fixed; z-index: 0`.
- 상단 66px 스트립은 공통 `.topbar`(배경 투명) 아래 의도된 Glass 페이지 배경. 결함성 회색 밴드 없음.
- 화면 우측 하단 원형 버튼은 제품 UI가 아니라 캡처 도구(Tabbit 트레이 런처) 오버레이. 제품 플로팅 버튼과 콘텐츠의 겹침 없음.

## #5673 Library 820×1180 — 결함 없음 (코드 변경 없음)

- `5673-library-820x1180-production.png`: 실운영 캡처.
- 계측: `.library-view` background `rgb(242,245,247)`, `z-index: 2` > `.glass-shell-portrait` (여성 이미지, rect x344 y62 w672 h1118) `z-index: 1`. 패널이 이미지 위에 정상 스택.
- 우측 경계 elementsFromPoint 최상위 = `.library-view`. 패널 내부로의 배경 bleed 없음. 패널 밖(상단/하단 스트립) 배경 노출은 의도된 디자인.
- `5028-calendar-390x844-production.png`: Calendar 390×844 가로 오버플로 없음(scrollWidth 380 ≤ 390).

## #5666 인증 모달 — 결함 확인 후 최소 수정 (apps/padiem-chat/static/history.css)

before/: 수정 전 실운영 계측. after/: 동일 스크립트, 수정 후 로컬 정적 서버 계측
(`/api/auth/status`만 스텁, 실제 클릭 경로 유지). 4테마 × 4뷰포트 전체 실측은 각 디렉터리 `auth-measurements.json`.

| 값 | before (전 테마 공통) | after |
| --- | --- | --- |
| `.auth-dialog::backdrop` | `rgba(0,0,0,.52)` + `blur(6px)` | 공통 `rgba(18,24,31,.38)` + `blur(10px)`, padiem-glass `rgba(22,30,38,.32)` + `blur(8px)` — settings-dialog 공통 딤과 동일 |
| `.auth-panel` (padiem-glass) | `var(--panel)` = `rgba(235,239,242,.46)` → 어두운 딤 위 합성 시 탁한 회색 | settings-panel과 동일한 Glass 그라디언트 + `blur(34px) saturate(112%)` + 흰 보더 |
| `.auth-panel` (dark) | 보더 `rgba(127,127,127,.24)` | 공통 다크 대화상자 보더 `#4b6478`, 텍스트 `#edf5fc` |
| `.auth-primary` (dark) | `#111` → 패널(#1a1b1f)에 묻힘 | `#a2d5f5` / `#132637` — 다크 테마 composer send 버튼과 동일 CTA |

- light/padiem-home/cinematic: 패널은 테마 변수 유지, 딤 완화만 적용. 인증 동작(폼·포커스·닫기) 변경 없음. CSS만 변경.
- 캡처 상태: login(4테마), signup/reset(padiem-glass·dark, 820×1180).
