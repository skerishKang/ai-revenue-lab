# 임미란 의원 홈페이지 프로토타입 (#5972)

독립 웹 프로토타입. 기존 운영 의원 페이지(`apps/padiem-chat/static/councillor/`)는 변경하지 않음.

## 실행
```bash
python -m http.server 8792 --directory apps/councillor-prototype
```
브라우저에서 http://127.0.0.1:8792/ 접속.

## 구조
- `index.html` — 단일 페이지, 5개 섹션(소개·의정활동·정책자료·미디어·소식)
- `static/styles.css` — 디자인 토큰 기반 반응형 스타일
- `static/app.js` — 의정활동 목록→상세, 검색·분류, 미디어 갤러리, 소식
- `static/miraen.json` — 기존 브랜드 데이터 재사용

## 검증
- 1440px / 768px / 390px 레이아웃 확인
- 키보드 접근성 (tabindex, role, Enter/Space)
- 실제 공식 자료 기반 (중앙선거관리위원회, 광주광역시의회, 전남광주통합특별시의회)

## 상태
시제품. 운영 배포 없음. Draft PR 예정.
