# 5ui-batch-20261024 — #5555·#5028·#5661·#5553·#5608 통합 개발 증거

PR #5705 (병합 `901598f7f2b3e87ede3193fc7a40f6bcc4fe0f7b`), 배포 run 40048295855 SUCCESS.
기준선 = 배포 전 실운영, live = 배포 후 실운영(`chat.padiem.net`).

## baseline/ (배포 전 실운영 캡처, Tabbit 로그인 세션)

chat-home / chat-pc-panel / claw-home / connectors / automation / meeting / library / calendar / util-speech @1440×900.
핵심 계측: 콘텐츠 레인 1440=622px·1920=988px(상한 1200, 좌측 고정), 스타터 카드 129↔176px, composer가 이미지에 5~6px 접근.

## after-local/ (수정 후 로컬 계측·칩 증거)

`results.json` — A/B/C/D 전 항목. 칩 4상태 요소 스크린샷(chip-*.png):
connected=녹색+체크 "PC 연결됨", connecting=액센트+시계 "연결 확인 중", disconnected=중립+슬래시 "컴퓨터 미연결", unavailable=적색+경고 "상태 확인 불가".

## live/ (배포 후 실운영)

- `chat-home-1920x1080-post.png`: 960px 캡 레인 적용 화면.
- `connectors-820x1180-post.png`: 통일된 불투명 시트 + 한 줄 헤더(디스클로저 없음) + 9카드 1열.
- `util-1440x900-post.png`: #5698 통합 util 디자인(공통 사이드바·액센트·배경 이미지) — 배포 후 최초 실운영 반영.

## 라이브 계측 (배포 후, 2026-10-24)

- Chat 레인: 1440=622px(x310, 불변), 1920=960px(x324), 2560=960px(x646 = 중앙 정렬), overflowX 0 전 구간.
- 5페이지 시트(820): connectors/automation/meeting/library/calendar 전부 `rgb(242,245,247)` — 프레임 통일. meeting 패널 플래튼(보더 0, 배경 투명).
- Connectors 디스클로저: 부재. 캘린더 오류 슬롯 강제 표기 시 제목 y 변화 δ0.
- 칩 라이브 전이: "연결 확인 중" → (서버 503) "상태 확인 불가" — 실서버 권위.

## util E2E (합성 자료, 실운영 실동작)

1. 축사: 합성 행사 정보로 초안 생성(663자) → 저장 → 라이브러리에 `합성 테스트 창립기념식` 파일 반영 확인.
2. SNS: 블로그 게시글 생성(1,335자, 탭 블로그/페이스북/인스타그램).
3. 회의정리·활동집: 기록 9건 중 1건 선택 → 책/활동집 초안 생성(2,047자).
