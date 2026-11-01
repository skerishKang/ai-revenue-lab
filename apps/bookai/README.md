# 북AI (BookAI)

읽고, 묻고, 기억하는 책. StoryMemory 1.1에서 분리한 앱이며 성경을 포함한 모든 책에 적용합니다. `apps/storymemory/`는 기존 1.0 앱입니다.

배포 대상은 새 Cloudflare Pages 프로젝트 `bookai`, 도메인은 `bookai.padiem.net`입니다. PR·머지·배포·도메인 연결은 CTO가 담당합니다.

```sh
npx -y wrangler@4.156.0 pages deploy apps/bookai/public --project-name bookai --branch main --keep-vars
```

배포 전에 `EXCLUDED_ASSETS.md`의 제외 자산을 확인합니다. 이 브랜치에서는 운영 배포나 비밀 변경을 하지 않습니다.

## 읽기 화면 저장

`bookai-bootstrap.js`가 같은 주소의 기존 localStorage 기록을 IndexedDB로 이전하고 캐시를 준비한 뒤 읽기 화면을 시작합니다. 원본 localStorage 기록은 삭제하지 않습니다. 기존 주소의 기록은 백업 파일을 내보내 북AI에서 불러옵니다.

읽기 위치·메모·밑줄·저장한 AI 대화는 `BookAIStorage`를 통해 `bookai-local-v1` IndexedDB에 저장됩니다. 메모 120개·표시 80개·주석 500개의 기존 잘림을 제거했습니다. 화면의 저장 완료 표시는 IndexedDB 커밋 이후에 표시합니다. 로그인하지 않아도 기기 저장이 작동합니다.

## 로그인과 자동 동기화

공통 로그인은 `client_id=b61`, 콜백은 `https://bookai.padiem.net/auth/callback`입니다. Worker의 HttpOnly 세션에서 확인한 계정 ID로 동기화합니다. 브라우저에는 서명 비밀을 보내지 않습니다.

`bookai-records.js`가 기록별로 안정적인 ID·책·위치·종류·수정 시각을 만들고, `bookai-local-db.js`가 기록과 전송 대기열을 함께 커밋합니다. `bookai-sync.js`는 로그인 후 앱 시작·30초 간격·온라인 복귀 때 GET since, 변경 후 모아서 POST합니다. 실패한 전송은 IndexedDB 대기열에 남겨 재시도합니다. 수정 시각이 큰 기록이 우선하며 삭제 표시도 다른 기기에 적용합니다. 규격 v1은 서버 도착 시각이 아닌 기록의 수정 시각을 기준으로 조회하므로, 시작·재연결·주기 조회와 업로드 직후에는 전체를 다시 대조하여 늦게 올라온 오프라인 기록도 회수합니다.

컴2 이슈 #6446의 규격 v1을 사용합니다. 여러 기록은 5MiB 이하 요청으로 나눕니다. 단일 기록 자체가 5MiB를 넘으면 기기 저장은 가능하지만 그 기록은 서버 규격상 전송 대기 상태로 남습니다. 같은 밀리초에 수정한 기록들은 경계를 겹쳐 조회하여 페이지 사이에서 누락되지 않게 합니다.

한 기기의 기록을 다른 로그인 계정으로 잘못 보내지 않도록 저장소의 동기화 계정을 고정합니다. 다른 계정이면 기기 기록은 보존하고 자동 전송을 멈춥니다.

필요한 Pages 비밀 이름(값은 CTO가 설정):

- `BOOKAI_AUTH_CLIENT_PRIVATE_JWK`
- `BOOKAI_COM2_SYNC_SECRET`
- `PADIEM_INGRESS_CLIENT_SECRET` (AI 입구)

`STORYMEMORY_MODEL`은 명시 AI 모델 덮어쓰기 설정입니다.

## 검증

`tests/bookai-reader-sync.browser.cjs`는 실제 읽기 화면에서 다음을 검증합니다.

1. 기존 715개 메모·AI 저장·밑줄/주석 및 읽기 위치 이전 후 내용 일치, 원본 보존.
2. 화면에서 6MiB 초과 메모 저장, 새로고침, 편집 화면에서 내용 전체 복원.
3. 오프라인 기록 저장 후 온라인 복귀 시 자동 전송.
4. 두 브라우저 기기의 독립 기록 병합·최신 수정 반영·삭제 전파와 재시작 후 유지.

컴2와 로그인 응답은 모의 서버로 검증하며 운영 서비스 접속 성공을 뜻하지 않습니다. `tests/bookai-sync-runtime.test.cjs`는 시작 순서·같은 시각의 620개 기록·요청 크기 분할도 검증합니다.

```sh
python -m http.server 18941 --bind 127.0.0.1 --directory apps/bookai/public
# Playwright와 Chrome이 있는 환경에서 B61_BASE_URL / B61_CHROME_PATH 설정 후 실행
node apps/bookai/tests/bookai-reader-sync.browser.cjs
node apps/bookai/tests/bookai-sync-runtime.test.cjs
```

`DB_MIGRATIONS/`, 기존 패치 노트와 자산 매니페스트는 원본 보관 자료입니다.
