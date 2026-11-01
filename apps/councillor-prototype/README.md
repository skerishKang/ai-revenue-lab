# 임미란 의원 홈페이지 V2 (#5972)

기존 운영 의원 페이지(`apps/padiem-chat/static/councillor/`)는 변경하지 않음.

## 실행
```bash
python scripts/build-dist
python -m http.server 8792 --directory apps/councillor-prototype/dist
```
브라우저에서 http://127.0.0.1:8792/ 접속.

## 구조
- `index.html` — 홈 (히어로·의정활동 카드·자료 수·소식/미디어/바로가기)
- `about.html` · `activity.html` · `policy.html` · `media.html` — 내부 페이지 4개 + `404.html`
- `static/styles.css` — 디자인 토큰 기반 반응형 스타일 (본문 16px · 이름표 14px · 누르는 곳 44px)
- `static/fonts/` — 자체 호스팅 웹폰트 (제목 마루부리 Bold 부분집합 · 본문 Pretendard), 라이선스 고지 포함
- `static/app.js` — 의정활동 목록→상세, 검색·분류, 미디어 갤러리, 소식, 테마
- `static/home.js` — 홈 전용 렌더러 (같은 데이터를 읽습니다)
- `static/miraen.json` — **내용 단일 소스.** 화면은 이 파일을 읽어 렌더링하고, 스크립트에는 내용을 복사하지 않습니다. `tests/`가 형식과 링크를 확인합니다.
- `site.config.json` — 배포 기준 주소(`baseUrl`) 한 곳. HTML·`robots.txt`·`sitemap.xml`의 `__BASE_URL__`을 빌드할 때 이 값으로 바꿉니다.
- `scripts/build-dist` — 배포 묶음 `dist/` 생성. html·static·robots·sitemap·404·favicon만 복사하고 docs·tests·README·scripts는 넣지 않습니다.

## 검증
```bash
python -m pytest apps/councillor-prototype/tests -q
```
- 휴대폰(≤900px) 하단 고정 메뉴, 헤더 이름=홈 링크, 페이지별 메뉴 순서 동일
- 공통 메타데이터(description · OG 1200×630 · canonical · favicon · lang="ko"), robots/sitemap/404
- 글자 크기 하한(본문 16px·이름표 14px)과 44px 누르는 영역
- 의정활동·소식·미디어가 `static/miraen.json` 형식과 링크 규칙을 지키는지, 정책 카드 링크가 겹치지 않는지
- 이미지가 WebP인지, 글꼴이 부분집합인지, `dist/`에 docs·tests·README·scripts가 없는지, `__BASE_URL__`이 남지 않는지
- 키보드 접근성 (tabindex, role, Enter/Space), `prefers-reduced-motion`

## 배포
`python scripts/build-dist`로 `dist/`를 만든 뒤 `dist/`를 배포합니다.
