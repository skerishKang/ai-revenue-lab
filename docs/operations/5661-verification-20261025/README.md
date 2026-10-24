# #5661 운영 검증 증거 (2026-10-25, CGI-UI LOCAL)

대상: `chat.padiem.net` (운영 정적 자산 = main `cccbb5b5a` — shared-six-panel-frame.css 등 4파일 diff 일치 확인).
방법: Tabbit 로그인 세션(강철원), 6뷰포트(390/820/1440/1920/2047/2560) Chat·Claw DOM computed 좌표 + 실캡처 3장.

## 계측 요약 (Chat↔Claw 동일성)

| 뷰포트 | conv rect (Chat=Claw) | composer 중심선 Δ | composer 폭 | portrait 간격* |
|---|---|---|---|---|
| 390 | x13 w364 | 0 | 362 (−2) | — (시트 위 의도) |
| 820 | x30 w760 | 0 | 792 (+32)** | — |
| 1440 | x309.6 w621.6 | 0 | 593.6 (−28) | −8 (잠긴 첫화면 오버랩) |
| 1920 | x324 w960 | 0 | 932 (−28) | +20 |
| 2047 | x389.5 w960 | 0 | 932 (−28) | +37.1 |
| 2560 | x646 w960 | 0 | 932 (−28) | +118 |

\* conv 우측 − portrait 좌측. ** 820은 ≤920px 독립 모바일 레인(+32는 동일 모바일 계약).

- Chat·Claw의 conversation/composer/H1/칩 rect가 6개 뷰포트 전부 픽셀 일치 (예: 2560 conv x646 w960, composer x660 w932 — 양측 동일).
- H1: 88px/520 (1440+), 64px(820), 27.3px(390). Claw 정체성 문구("작업하는 클로입니다.") 유지 — claw-home-1440x900.png.
- composer 과다 확장 없음: 1920/2047/2560 모두 932px 캡(#5705). 좌측 거터 +14, 우측 −14(의도 인셋). #5725가 지적했던 2047 left 불일치 해소(conv x389.5 ↔ composer x403.5).
- 초광폭 배분: 2560에서 레인 좌측 646·아트워크 간 118px — 패널 중앙 정렬로 균등(chat-home-2560x1200.png).

## PC 연결 패널 (1440, 열림)
- 패널: absolute, z13, 554×150, composer 상단 위 배치. 카드 y 477→477 (밀어내기 없음).
- 관찰(사소): 짧은 콘텐츠에서 패널 하단이 composer 프레임 상단과 ~8px 접촉. textarea 침범 없음·기능 영향 없음 — 별도 관찰 기록으로만 남김.

## 모바일 390
- overflowX 0, send/mobileMenu/칩 전부 44×44, composer 하단 0px 간격(dvh 고정).

## 판정
PASS — 차단 결함 없음. 캡처: chat-home-1440x900.png / chat-home-2560x1200.png / claw-home-1440x900.png.
