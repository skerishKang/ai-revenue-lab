# Chat/Claw 화면 눈 점검 보고서 — 2026-11-19

- 점검 대상 커밋: `fdacde354` (11-18 배포 전 점검 보고서 시점의 main)
  - 점검 후 main에 8개 커밋이 더 올라옴(locale 묶음 분리 #8000, 토큰 정리 #7997·#7998 등).
    색 토큰 정리와 겹치는 항목은 수정 전 재확인 권장.
- 환경: 로컬 개발 서버(`app.local_cpython.build_app()`, mock 런타임 + 시험용 가짜 비밀번호 계정).
  운영 서버·운영 DB·실제 로그인·PC 연결은 일절 사용하지 않음.
- 대상: 5테마(padiem-home · light · dark · cinematic · padiem-glass) × 3크기(1440×900 · 1440×768 · 390×844)
- 방법: Playwright 캡처 249장(`captures/`) + 5테마 접촉시트 46장(`sheets/`) + 프로그램 점검
  (가로 스크롤·화면 밖 단추 — 화면×테마×크기 105셀 전부 이상 없음)
- 화면 목록: 첫 화면(게스트·로그인), 새 대화(빈 화면·답변 중·답변 끝), 첨부, 프로젝트,
  유틸(목록·회의정리·PDF→Markdown), 캘린더, Claw(작업 허브·실행 기록·자동화), PC 연결 카드,
  새 소식, 의견 보내기, 도움말

## 결과 요약

- 심각도: **못 씀 0건 / 불편 2건 / 보기 4건**
- 이슈(화면별 1개씩 5건):
  - Claw 화면 — 말풍선 대비: #{ISSUE_CLAW}
  - Chat 화면 — 빈 전송 안내 겹침 + 툴팁 잔존: #{ISSUE_CHAT}
  - 연결 화면 — padiem-glass 카드 대비: #{ISSUE_CONNECTORS}
  - 유틸 PDF→Markdown — 어두운 테마 흰 패널: #{ISSUE_PDFMD}
  - 프로젝트 — 밝은 테마에서 어두운 다이얼로그·패널: #{ISSUE_PROJECT}

## 문제 표

| 화면 | 테마 | 크기 | 문제 | 캡처 | 심각도 |
|---|---|---|---|---|---|
| Claw 대화 | padiem-home · cinematic | 1440×900, 390×844 | 사용자 메시지 말풍선 안 글자가 배경과 거의 같은 어두운 색이라 읽을 수 없음. light·dark·padiem-glass는 정상 | `captures/claw-runs-padiem-home-1440x900.jpg`, `captures/claw-runs-cinematic-1440x900.jpg`, `captures/claw-runs-padiem-home-390x844.jpg`, `captures/claw-runs-cinematic-390x844.jpg` | 불편 |
| Chat 입력창 | 전체 공통 | 1440×900, 390×844 | 빈 메시지로 전송 클릭 시 빨간 안내(`글자를 입력하세요`)가 음성 버튼·전송 버튼 위에 겹쳐 절반가량 잘림 — 전송이 왜 안 된지 읽기 어려움 | `captures/chat-empty-send-error-1440x900.jpg`, `captures/chat-empty-send-error-390x844.jpg` | 불편 |
| Chat 입력창 | 전체 공통 | 390×844 | 전송 클릭 후 `메시지 전송` 툴팁이 사라지지 않고 입력창 오른쪽 위에 남아 겹침(마우스 환경과 차이 가능 — 확인용) | `captures/chat-send-tooltip-after-click-390x844.jpg` | 보기 |
| 연결 | padiem-glass | 1440×900, 390×844 | 카드 경계선이 거이 안 보이고 라벨 대비 낮음. 나머지 4테마는 정상 | `captures/pc-card-padiem-glass-1440x900.jpg`, `captures/pc-card-padiem-glass-390x844.jpg` | 보기 |
| 유틸 PDF→Markdown | dark · cinematic | 1440×900, 390×844 | 도구 안쪽 패널만 흰 배경이라 어두운 화면 속에 튐(글자는 읽힘) | `captures/util-pdfmd-dark-1440x900.jpg`, `captures/util-pdfmd-cinematic-1440x900.jpg`, `captures/util-pdfmd-dark-390x844.jpg` | 보기 |
| 프로젝트 | padiem-home · light 등 밝은 테마 | 1440×900, 390×844 | 생성 다이얼로그와 활성 프로젝트 정보 패널이 밝은 테마에서도 짙은 어두운 배경(글자는 읽힘) | `captures/project-form-light-1440x900.jpg`, `captures/project-form-padiem-home-390x844.jpg`, `captures/project-created-padiem-home-390x844.jpg` | 보기 |

## 확인·정정 사항 (문제 아님 — 이슈 만들지 않음)

- **390 가로 스크롤 없음**: 105셀(화면×테마×크기) 프로그램 점검에서 `overflowX=0`, 화면 밖 단추 0건.
- **padiem-glass 첫 화면 390 첨부 안내 미표시**: glass 전용 규칙
  (`padiem-glass-brand-polish.css`, `shared-six-panel-frame.css`)의 의도된 숨김.
  composer 자체는 832px에서 화면(844px) 안에 들어옴 — 잘림 아님.
- **padiem-glass Claw의 '웹에서 Excel 원본 보관' 바 미표시**: `claw-focus-layout.css:388`의
  의도된 규칙(Excel을 선택하면 상세가 열리며 표시). 다른 4테마와 다르게 보이는 것은 설계.
- **유틸 도구 제목의 파란 포커스 링**: 라우트 전환 시 헤딩 포커스(`util-app.js`) 때문에
  스크립트 포커스가 걸린 캡처 환경 artifact. 실제 마우스 조작에서는 `:focus-visible`이 아니라 링이 안 보임.
- **PC 연결 카드의 '로그인' 표시**: 세션을 UI 밖에서 먼저 만든 캡처 artifact(서버 세션은 유효).
- **사이드바 하단(계정 카드 + 법적 링크만)**: #7780의 의도된 프로필 메뉴 이동 설계.
- **자동화 '규칙을 불러오지 못했습니다' · 캘린더 '다시 시도' 칩**: mock 로컬 환경 특성(문구·자리는 정상).

## 제한

- 시험용 가짜 계정만 사용. 실제 로그인·가입·PC 연결·운영 접속 없음.
- 프로젝트 생성은 로컬 origin 가드(공개 기준 https) 때문에 시험 도구에서 Origin 헤더만 교정해 캡처.
- Claw 실행 기록의 waiting_approval 카드는 앱이 패널을 다시 숨겨 미캡처(실행 기록 목록 자체는 캡처됨).
- 답변 중 화면은 느린 스트림 모사로 캡처(1440×900에서 '준비 중' 칩 확인).
