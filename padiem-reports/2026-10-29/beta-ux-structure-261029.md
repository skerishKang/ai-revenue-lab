# 베타 UX 구조 4건 — 2026-10-29 (아스트라2)

PR **#6108**(구조 1·2번, 머지 `c84e229d5`), PR **#6112**(견적서·테마 3·4번)로 나눠 머지.
캡처: `tools/beta-ux-capture.py`(`--tag` 전후 쌍, `--theme` 통과, 픽셀에서 되읽은 대비 수치) — 1440/390, 기본 테마 = padiem-glass.

## 1) 축사 PC 참고 → 폼 최상단 '참고 글'

| 측정 | BEFORE | AFTER |
|---|---|---|
| `#utilSpeechRef` legend 존재 | 없음(null) | "참고 글" 표시 |
| 참고 fieldset이 폼 첫 자식 | false | true |

- SNS(#6098)와 같은 `util-fieldset`+legend 언어, 마운트(`utilSpeechPcRef`) 이동, 필드명 변경 없음.
- 증거: `before-util-speech-{desktop,mobile}.png` → `after-util-speech-{desktop,mobile}.png`

## 2) 공용 가져오기 대화상자

| 측정 | BEFORE | AFTER |
|---|---|---|
| 루트 [이전 폴더] disabled | false | true(시각적으로도 45%) |
| 모바일 도구 행 한 줄 | false(2줄, 97px) | true(45px) |

- 루트 비활성은 `paintList()`가 경로와 동기화(폴더 진입 시 재활성, 저장 모드 포함). 비활성 프레스는 서버 요청 없음(하니스 검증).
- 모바일은 aria-label 유지한 채 화살표 아이콘화 + `box-sizing: border-box` + 검색 input `min-width: 0`(size 속성 최소폭이 찾기 버튼을 밀던 원인). 44px 터치 하한 유지.
- 증거: `before-pc-exchange-dialog-*.png` → `after-pc-exchange-dialog-*.png`

## 3) 견적서 로그아웃 — 빈 select 대신 안내

| 측정 | BEFORE | AFTER |
|---|---|---|
| signin 힌트 | 없음 | "로그인하면 내 양식과 등급을 고를 수 있어요" + 로그인 버튼 |
| select 라벨 3개 | 표시(옵션 0) | 전부 숨김 |
| capabilitychange 로그인 시 | refresh()(기존) | 동일 + 힌트 해제·필드 복원 |

- 이벤트는 기동 직후(/api/auth/status 응답 후)에도 발화 — 게스트 판정은 추측 없이 제품 신호로만.
- 로그인 버튼은 계정 영역의 자체 진입(#loginButton) 위임. 로그인 후 동작(entry-only 포함) 변경 없음.
- 증거: `before-quote-quote-dialog-*.png` → `after-quote-quote-dialog-*.png`

## 4) glass 테마 입력 테두리 대비 (WCAG 1.4.11 비텍스트 3:1)

렌더링 픽셀에서 되읽은 수치(선언색 아님). SNS 행사명 input, 데스크톱 기준:

| 테마 | BEFORE | AFTER |
|---|---|---|
| padiem-glass(기본) | 1.06 | **5.52** |
| light | 1.28 | **4.10** |
| padiem-home | 1.27 | **4.03** |
| cinematic | 1.44 | **4.43** |
| dark | 2.00 | **4.32** |
| 견적서 select(glass) | 1.18 | **5.66**(모바일 5.70) |

- 수단: 입력 전용 토큰 `--input-border-strong` 테마별 정의(glass `#56616b`, light·home `#767e8a`, dark·cinematic `white .45`) + glass 견적서 대화상자 입력 fill을 카드 불투명도(0.86 white)로 고정(토큰만으로 2.77이었던 원인 = 자체 blur 뒤 페이지가 fill을 좌우).
- 중간 수치도 증거로 남김: 토큰만 적용한 상태 2.77(after-quote 1차 캡처 → fill 수정 후 재캡처로 대체, 본문에 기록).
- 증거: 테마별 `before-<theme>-util-sns-*.png` / `after-<theme>-util-sns-*.png`, `beta-ux-20261029-{before,after}-<theme>-summary.json`

## 목록에만 올린 것 (전역 변경 없음)

- glass `--line: rgba(255,255,255,.38)`은 카드 헤어라인으로는 여전히 저대비 — 연결 화면 재설계(아스트라3)가 이 값을 쓰므로 건드리지 않았다. 연결 화면 작업 시 카드 테두리만 별도 토큰화 제안.
- 견적서 대화상자의 `--border` 폴백(`rgba(127,127,127,.28)`)도 범용 저대비 — 이번에는 `--input-border-strong` 폴백 사슬로 입력만 해소. 다른 대화상자(설정 등)의 입력은 별도 항목.
- dark 테마 util 입력 fill(#1a232d) 자체는 문제 없음(대비 4.32로 통과).

## 테스트

- `pc_file_exchange_harness.js`: 루트 비활성/재활성/비활성 프레스 무요청.
- `test_beta_ux_structure_261029.py`, `test_beta_ux_quote_access_261029.py`(신규), `test_b66_quote_signin_hint_261029.mjs`(신규).
- 고정 문구 갱신(RED→GREEN 확인): test_5799 fieldset 3→4, 축사 외곽선 토큰, test_4428/test_b66_quote_ui_bridge 리스너 형태.
- 회귀: util·quote·theme·glass 관련 100+ 케이스 통과.
