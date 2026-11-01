# 북AI (BookAI)

읽고, 묻고, 기억하는 책. 북AI는 기존 StoryMemory 1.1을 분리한 독립 앱이며 성경을 포함한 여러 책을 지원합니다. `apps/storymemory/`는 별도 1.0 앱입니다.

배포 대상(예정): Cloudflare Pages 프로젝트 `bookai`, 도메인 `bookai.padiem.net`. 이 주소와 프로젝트가 이미 설정되었다는 뜻은 아닙니다. 배포 및 도메인 연결은 CTO가 담당합니다.

배포할 때는 자산 누락 여부를 `EXCLUDED_ASSETS.md`와 대조하고 승인된 계정에서 프로젝트 이름을 명시합니다:

```sh
npx -y wrangler@4.156.0 pages deploy apps/bookai/public --project-name bookai --branch main
```

AI 연결에 필요한 Pages 비밀 이름은 `PADIEM_INGRESS_CLIENT_SECRET`이며, 값은 저장소에 넣지 않습니다. `STORYMEMORY_MODEL`은 선택적 모델 경로 설정입니다. IndexedDB 기반은 준비되어 있으나 실제 화면 저장 전환과 파디엠 로그인·컴2 동기화는 아직 구현되지 않았습니다.

`public/`은 1.1 통합 작업 브랜치에서 가져온 앱 파일입니다. `DB_MIGRATIONS/`, 패치 노트와 기존 매니페스트는 원본 참고 자료입니다.


로그인·컴2 연결 준비: Pages 비밀 이름은 `BOOKAI_AUTH_CLIENT_PRIVATE_JWK`와 `BOOKAI_COM2_SYNC_SECRET`입니다. 비밀 값은 저장소에 넣지 않습니다. Worker 경로는 준비되었으나, 읽기 화면의 IndexedDB 전환과 클라이언트 자동 동기화는 아직 연결되지 않았습니다. 배포 준비가 끝난 것으로 간주하지 마세요.
