# COM2 스테이징 큐 요청값 (#6305)

| 항목 | 제안 / 확인 필요 |
|---|---|
| 프로세스 포트 | `8830` 확정(2026-10-31). 8790은 `lovetree-api`가 점유, 예비 `8831` |
| DB 경로 | `/opt/padiem/mesh-queue-staging/queue.db` 확정(2026-10-31). 디렉터리 0700·DB 0600, owner `padiem-mesh` |
| HTTPS origin | `https://queue-staging.padiem.net` 제안. Qoder가 Tunnel·DNS와 함께 확정 |
| 인증 | 운영과 별도 시크릿. 값은 전달·기록하지 않음 |
| 실행기 | 합성 전용, 운영 실행기·실제 PC 접촉 금지 |

> 2026-10-31 정정: 초안의 8790은 컴2에서 `lovetree-api.service`(127.0.0.1:8790)가 이미 사용 중이어서 쓸 수 없다. 87xx/88xx 조사에서 8830·8831이 WSL과 Windows 모두 비어 있고 문서·계획에 없어, 8830을 스테이징 큐 포트로 확정하고 8831을 예비로 둔다. 근거와 실측값은 `STAGING_QUEUE_SETUP_20261031.md`.

2026-10-31에 스테이징 큐 인스턴스(유닛 `padiem-mesh-queue-staging`, DB `/opt/padiem/mesh-queue-staging/queue.db`, 127.0.0.1:8830)를 구축했다. 운영 큐·실행기·파일 레인·cloudflared·lovetree-api는 변경·재시작하지 않았다. Cloudflare Tunnel·DNS·origin 등록, 스테이징 Worker E2E, 합성 실행기 연결은 아직 하지 않았다.
