# #7811 C4 후속: padiem-bright-readability.css 흡수

## 결과
- 기준: main 631f10576
- cinematic body 배경과 body::before 배경 2규칙을 padiem-themes.css 동일 대상의 기존 규칙으로 흡수
- 중요도(!important) 유지, 색상 수치 추가 없음, 규칙 수 2개 감소
- computed: 5테마×2폭×4상태×4의사상태 = 160/160 동일 (CSS 배경 URL 호스트·포트만 정규화)
- pixel: 5테마×2폭×13화면 = 130/130 완전 동일
- control: 같은 코드 130/130 완전 동일
- 의도적 배경 변경 2건 모두 픽셀 차이 탐지
- 신규 회귀 테스트 2개, C4 집중 테스트 29개, 테마 관련 43개, 밝기·베일 관련 15개 통과

## 구조 감사
| 항목 | 전 | 후 | 변화 |
|---|---:|---:|---:|
| css_rules | 4353 | 4351 | -2 |
| css_important | 404 | 404 | +0 |
| css_color_literals | 918 | 916 | -2 |
| css_color_literals_unthemed | 280 | 280 | +0 |
| css_themed_rules | 769 | 767 | -2 |
| css_themed_important | 92 | 92 | +0 |

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
