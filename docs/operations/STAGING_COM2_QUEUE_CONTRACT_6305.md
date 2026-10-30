# COM2 스테이징 큐 요청값 (#6305)

| 항목 | 제안 / 확인 필요 |
|---|---|
| 프로세스 포트 | `8790` 제안. Qoder가 운영과 충돌하지 않는지 확인 |
| DB 경로 | `/opt/padiem/mesh-queue-staging/queue.db` 제안. Qoder가 실제 호스트·권한 확인 |
| HTTPS origin | `https://queue-staging.padiem.net` 제안. Qoder가 Tunnel·DNS와 함께 확정 |
| 인증 | 운영과 별도 시크릿. 값은 전달·기록하지 않음 |
| 실행기 | 합성 전용, 운영 실행기·실제 PC 접촉 금지 |

현재 PR은 설정 생성과 격리 검사만 포함하는 초안이다. DB 생성·마이그레이션·실제 배포 workflow, 운영 인증 연동, 실제 Worker 부팅과 E2E는 아직 구현·검증하지 않았다. Qoder 확정값에 따라 허용 origin을 변경한다.
