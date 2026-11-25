# 임미란 의원 홈페이지 V2 (#5972)

기존 운영 의원 페이지(`apps/padiem-chat/static/councillor/`)는 변경하지 않음.

## 실행
소스 HTML은 본문만 담고 머리·바닥·하단 탭은 `partials/`에서 빌드할 때 끼워 넣습니다.
따라서 로컬 미리보기도 배포와 같은 순서를 따릅니다.

```bash
python apps/councillor-prototype/scripts/build-dist
python -m http.server 8792 --directory apps/councillor-prototype/dist
```
브라우저에서 http://127.0.0.1:8792/ 접속. 목록·카드 HTML도 `scripts/prerender.py`가
이 빌드에서 만들므로, 소스 트리를 직접 서빙하면 내용이 비어 보입니다.

## 구조
- `partials/` — 공통 head·header·footer·tabbar 조각과 `pages.json`(페이지별 제목·설명·canonical·OG·활성 탭 값). `scripts/assemble.py`가 조립합니다.
- `index.html` — 홈 본문 (히어로·의정활동 카드·자료 수·소식/미디어/바로가기)
- `about.html` · `activity.html` · `policy.html` · `media.html` — 내부 페이지 본문 4개 + `404.html`
- `static/styles.css` — 디자인 토큰 기반 반응형 스타일 (본문 16px · 이름표 14px · 누르는 곳 44px)
- `static/fonts/` — 자체 호스팅 웹폰트 (제목 마루부리 Bold 부분집합 · 본문 Pretendard), 라이선스 고지 포함
- `scripts/prerender.py` — 목록·카드·소식·더 보기 목록을 만드는 유일한 곳
- `static/app.js` — 이미 그려진 DOM에 검색·분류·상세·크게 보기·테마만 붙입니다
- `static/home.js` — 홈 미디어 카드에 크게 보기 동작만 붙입니다
- `static/miraen.json` — **내용 단일 소스.** 화면은 이 파일을 읽어 렌더링하고, 스크립트에는 내용을 복사하지 않습니다. `tests/`가 형식과 링크를 확인합니다.
- `site.config.json` — 배포 기준 주소(`baseUrl`) 한 곳. HTML·`robots.txt`·`sitemap.xml`의 `__BASE_URL__`을 빌드할 때 이 값으로 바꿉니다.
- `scripts/build-dist` — partials와 본문을 조립한 뒤 prerender를 적용해 `dist/`를 만듭니다. static·robots·sitemap·favicon만 복사하고 docs·tests·README·scripts는 넣지 않습니다. 내부 메뉴 링크는 `dist/`에서만 깨끗한 주소로 바꿉니다.
- `scripts/check-links` — 공개한 외부 링크를 전부 GET해 4xx·5xx·시간초과를 보고합니다. PR이 아니라 주 1회 워크플로가 실행합니다.

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

## 새 소식 유지 관리

방문자에게 보이는 화면이 바뀌면 같은 PR에서 static/miraen.json의 news에 한 줄 더합니다. 날짜·제목·변경 내용 2~4줄을 기록합니다. 빌드에서 정적 HTML을 만듭니다.
