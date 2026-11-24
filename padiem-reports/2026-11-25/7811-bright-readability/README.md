# #7811 C4 bright-readability 흡수 최종 재검증

## 변경
- cinematic body·body::before 배경 규칙 2개를 기존 padiem-themes.css의 동일 선택자에 흡수
- 이관 뒤 새로 생긴 !important 2개 제거. 이동 대상 padiem-themes.css의 !important 13→13, 전체 CSS 371→369
- CSS 규칙 4353→4351, 색상 리터럴 910→908, 새 !important/색상 수치 0
- CSS 원문을 비교하는 신규 시험 삭제. 기존 테마 소유권 시험은 본래 동등성 조건 그대로 유지하며 소유 시트만 정합화
- 구조 ratchet 및 테마 계약 집중 테스트 28개 통과

## COM2 최신 main 재검증
- 기준 main c328cfaf3ba1cf4b75c2d8712c04de7f9dc204f4, 작업 HEAD 8446c9bd3eddf7ce1c5fbbfaa4174d82955cbe48
- 계산값: 5테마×2폭 10/10 동일, DOM/의사요소 계산 CSS 선언 비교
- 픽셀: 5테마×2폭 10/10 차이 0, 상태 마커 및 렌더 안정성 검증
- 동일 코드 제어쌍: 5테마×2폭 10/10 차이 0
- 의도적 body와 body::before 배경 변경 2/2 검출
- 이전 우선순위 정리 전 전체 계산값 160/160·픽셀130/130·제어쌍130/130 검증은 *_before_priority_cleanup.json에 별도 보존. 최종 판정에는 정리 후 COM2 결과를 사용.
- 배경 이미지 URL 비교는 호스트·포트만 정규화하고 경로·파일명을 그대로 보존

## 구조 수치
| 지표 | main | PR | 변화 |
|---|---:|---:|---:|
| css_rules | 4353 | 4351 | -2 |
| css_themed_rules | 769 | 767 | -2 |
| css_important | 371 | 369 | -2 |
| css_themed_important | 86 | 84 | -2 |
| css_color_literals | 910 | 908 | -2 |
| css_color_literals_unthemed | 272 | 272 | +0 |
| css_rules_by_file/padiem-themes.css | 113 | 113 | +0 |
| css_important_by_file/padiem-themes.css | 13 | 13 | +0 |
| css_rules_by_file/padiem-bright-readability.css | 23 | 21 | -2 |
| css_important_by_file/padiem-bright-readability.css | 13 | 11 | -2 |

## 남겨 둔 규칙과 이유 (총 21규칙)
| 묶음 | 규칙 수 | 유지 이유 |
|---|---:|---|
| 밝은 테마 사이드바 항목·아이콘·배지·제목·호버 | 5 | light/home 전용 토큰과 탐색 상태 특이성이 달라 부품 원본과 직접 합치면 계층/대비가 변함 |
| 밝은 테마 작성 도구 기본·호버·선택 | 3 | 버튼 상태와 disabled 스코프가 부품 공통 규칙과 달라 별도 상태 정리가 선행돼야 함 |
| 마이크로카피 및 dark/cinematic 사이드바 제목 | 2 | Glass 제외 및 두 어두운 테마의 범위가 별도로 정의되어 공통 타이포그래피 통합 시 화면이 달라짐 |
| cinematic 사이드바·상단·시작 카드·작성창·셸 장식 | 5 | 다른 시트의 동일 대상에 여러 !important·그림자·테마 규칙이 겹쳐 우선순위 조사 후 개별 흡수 필요 |
| 휴대폰 대화 중 테마 선택기(기본/단추/선택/포커스/펼침) | 5 | 대화 상태·포커스 전용 배치로, 390폭과 소프트 키보드 상태의 구조적 동등성까지 확인 후 이관 |
| 420폭 이하 밝은 홈 제목 | 1 | 밝은 테마 전용 폰트 메트릭을 보존해야 하므로 홈 레이아웃 체인 통합 전까지 유지 |

## 증거
- PNG 7장: light·cinematic 전후 4장, 변조 전후 2장, 변조 diff 1장. manifest에 크기·SHA256 기록
- computed.json, pixel.json, control.json, tamper.json, audit.json, pytest.log


## 증거
- PNG 7장(전후 및 변조·diff), manifest.json의 SHA256·크기 확인
- computed.json, pixel.json, control.json, tamper.json, audit.json, pytest.log은 수정 후 재검증 결과
