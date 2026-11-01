# 임미란 의원 홈페이지 V2 (#5972)

기존 운영 의원 페이지(`apps/padiem-chat/static/councillor/`)는 변경하지 않음.

## 실행
```bash
python -m http.server 8792 --directory apps/councillor-prototype
```
브라우저에서 http://127.0.0.1:8792/ 접속.

## 구조
- `index.html` — 홈 (히어로·의정활동 카드·자료 수·소식/미디어/바로가기)
- `about.html` · `activity.html` · `policy.html` · `media.html` — 내부 페이지 4개 + `404.html`
- `static/styles.css` — 디자인 토큰 기반 반응형 스타일 (본문 16px · 이름표 14px · 누르는 곳 44px)
- `static/fonts/` — 자체 호스팅 웹폰트 (제목 마루부리 Bold 부분집합 · 본문 Pretendard), 라이선스 고지 포함
- `static/app.js` — 의정활동 목록→상세, 검색·분류, 미디어 갤러리, 테마
- `static/home.js` — 홈 전용 렌더러
- `static/miraen.json` — **내용 단일 소스.** `app.js`·`about.html`에 보이는 문구는 이 파일과 같아야 하고, `tests/`가 그 일치를 확인합니다.
- `robots.txt` · `sitemap.xml` — 검색엔진용. canonical·OG의 기준 주소는 `https://councillor-prototype-v2.pages.dev`입니다.
- `.assetsignore` — `docs/`·`tests/`·README는 배포에서 제외

## 검증
```bash
python -m pytest apps/councillor-prototype/tests -q
```
- 휴대폰(≤900px) 하단 고정 메뉴, 헤더 이름=홈 링크, 페이지별 메뉴 순서 동일
- 공통 메타데이터(description · OG 1200×630 · canonical · favicon · lang="ko"), robots/sitemap/404
- 글자 크기 하한(본문 16px·이름표 14px)과 44px 누르는 영역
- 내용이 `static/miraen.json`과 같은지, 정책 카드 링크가 겹치지 않는지
- 이미지가 WebP인지, 글꼴이 부분집합인지, 배포 제외 목록
- 키보드 접근성 (tabindex, role, Enter/Space), `prefers-reduced-motion`

## 배포
Cloudflare Pages 정적 배포. 빌드 단계 없음. 루트(`apps/councillor-prototype`)를 그대로 올리면
됩니다.
