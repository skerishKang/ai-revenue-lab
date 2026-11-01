# COM2 전환 후 24시간 관찰 — #5479·#6127 종결 판단 근거 (2026-11-01)

```text
DOC_ROLE=POST_CUTOVER_24H
STATUS=종결 완료 — #5479 PASS · #6127 PASS · closeable=YES (CTO가 컴2에서 직접 실행)
RELATED=deploy/host-com2/observe/, PR #6455, PR #6444, issues #5479·#6127,
        docs/operations/CHAT_COM2_RUNBOOK.md §8, docs/operations/CHAT_COM2_RUNBOOK.md §8-2
작성: 아스트라3(COM1) / 2026-11-01 21:46 KST
종결: CTO(컴2 직접 실행) / 2026-11-01 21:50 KST — 결과는 #5479·#6127 이슈 댓글
```

## 0. 한 줄 판정 (종결)

- **#5479(Python Worker 동시성 503·NoGilError): PASS — 종결.** 관측 창 24시간에서
  `NoGilError` 0건(`PyProxy` 0건), 재시작 0회.
- **#6127(`/api/auth/status`·`/api/projects` 간헐 500): PASS — 종결.** Chat 5xx 집계가
  가능했고(2,503 요청), `/api/auth/status`·`/api/projects` 5xx는 **0건**.
- **판정: `closeable=YES`** — 스크립트 종결 3조건(24h 창 커버·NoGilError 0·#6127 라우트
  5xx 0)이 모두 참. `window_covers_full_24h=true`(24.000h).
- 보고 시점(11-01 21:46 KST) 운영 확인: `https://chat.padiem.net/health` →
  **HTTP 200** `{"status":"ok", "runtime":"b14", "b14_configured":true}`.

## 0-1. 집계 원본 (CTO, 컴2에서 실행)

- 실행: `deploy/host-com2/observe/post_cutover_report.py --since
  2026-10-31T21:07:00+09:00 --until 2026-11-01T21:07:00+09:00`(읽기 전용, journald).
- 결과 댓글: #5479(2026-11-01T12:50:48Z)·#6127(12:50:50Z) — 이 문서 §4의 표는 그 값이다.

## 1. 관측 도구 (확정)

| 항목 | 내용 |
| --- | --- |
| 스크립트 | `deploy/host-com2/observe/post_cutover_report.py` — **COM2 호스트에서 실행**(journald·systemctl만 사용) |
| 출처 | PR #6455(feat(com2): post-cutover observation report + 24h close gate) |
| 자가검증 | `python -m unittest discover -s deploy/host-com2/observe/tests` → **15 tests OK**(11-01, COM1에서 실행 — 실제 COM2 접속 없음, Windows/Linux 어디서나 돈다) |
| 보조 | `.github/scripts/chat_post_cutover_smoke.py`(PR #6444) — health·게스트 페이지·asset·auth status 실측 |
| 비밀·개인정보 | 원본 로그 줄·본문·쿼리·헤더·쿠키·클라이언트 주소·식별자·request id·비밀 값을 출력하지 않는다(스크립트 계약) |

### 실행 (COM2에서, 종결 판단용 정확한 창)

```bash
python3 deploy/host-com2/observe/post_cutover_report.py \
  --since 2026-10-31T21:07:00+09:00 \
  --until 2026-11-01T21:07:00+09:00 \
  --json-out /tmp/post-cutover-20261101.json
```

### 종결 3조건 (스크립트 README 인용 — 세 조건이 모두 참일 때만 닫는다)

1. `window_covers_full_24h=true` — 창이 전환 시각부터 24시간 뒤까지를 모두 덮는다.
2. `#5479.pass=true` — `padiem-chat-com2` journald 창에서 `NoGilError` 0건
   (`PyProxy`는 별도 표시, 종결 조건은 NoGilError 0).
3. `#6127.pass=true` — Chat 5xx 집계가 **가능**하고, `/api/auth/status` 5xx 0,
   `/api/projects`와 그 하위 5xx 0.

`#6127=UNKNOWN`·`5xx 집계 불가`는 "0건"이 아니다 — **닫지 않는다**. `counts=null`은
journald를 읽지 못했다는 뜻이며 0으로 해석하지 않는다.

## 2. 관측 창과 배포·재시작 시각

| 시각 (KST) | 사건 | 집계 표기 |
| --- | --- | --- |
| 10-31 21:07 | 컷오버(운영 → COM2 8798) | 창 시작 |
| 11-01 17:25 | 재배포 | 배포 중 |
| 11-01 17:55 | 배포·재시작 | 배포 중 |
| 11-01 18:31 | 배포·재시작 | 배포 중 |
| 11-01 19:27 | 배포·재시작 | 배포 중 |
| 11-01 19:41 | 배포·재시작 | 배포 중 |
| 11-01 20:04 | 배포·재시작 | 배포 중 |
| 11-01 21:07 | 관측 창 종료 | 창 끝 |

- 배포 6건의 시각은 CTO 제공(11-01 지시)이다. COM2 journald의 유닛 시작 기록으로
  실측 대조하는 것을 권한다(`journalctl -u padiem-chat-com2 --since … | grep Started`).
- 집계 규칙: 각 배포 시각 ±10분 구간의 오류는 **"배포 중"**으로 분리해 판정에서 제외한다.

## 3. 집계 방법 (창: 10-31 21:07 ~ 11-01 21:07 KST)

| 항목 | 방법 |
| --- | --- |
| 요청 수·5xx 수·비율 | Chat은 앱의 `http_request` 이벤트(`status`·`route`) 우선, 없으면 uvicorn 접근 로그, 둘 다 없으면 `5xx 집계 불가`(`available=false`) |
| 503·500 라우트별 상위 | 경로 정규화(쿼리 제거, `/api/projects/*` 접기) 후 건수 순 표 — 원래 경로는 문서에 남기지 않는다 |
| 403 | 11-01 #6559 배포 뒤 생긴 403은 **원인이 별도 확정**(앞단 검증 replay DB를 `/mnt/d`(9p)에 두면 잠금 경쟁으로 정상 서명 요청도 403 — RUNBOOK §8-2, 11-01부터 검증 직렬화). 따라서 403은 일반 5xx·인증 실패와 **별도 행**으로 분리해 표기하고 #6127 판정에 넣지 않는다 |
| 재시작·크래시 루프 | `systemctl show -p NRestarts`(누적 카운터, 창 합계와 다를 수 있음) + 창 내 장애 구간(예: §8-1 — `ReadWritePaths` 밖 쓰기 → readonly database 크래시 루프) |
| Traceback·ERROR·NoGil·PyProxy | 3개 유닛(`padiem-chat-com2`, `padiem-p01`, `padiem-b14`) journald 건수 |
| health | 실행 시점 1회(창 전체 가용성 아님) |

P01·B14는 접근 로그가 꺼져 있어(unit `--no-access-log`, `access_log=False`) 5xx
집계가 불가하다 — 이는 Chat의 #6127 판정을 막지 않는다(README 규칙).

## 4. 집계 결과 (CTO 실행 — #5479·#6127 이슈 댓글 값)

창 2026-10-31 21:07 ~ 11-01 21:07 KST, **24.000h, full_24h=YES**:

| 유닛 | 상태 | 재시작 | NoGilError | PyProxy | 5xx |
| --- | --- | --- | --- | --- | --- |
| padiem-chat-com2 | active | 0 | **0** | 0 | 55 / 2,503 요청 |
| padiem-p01 | active | 0 | 0 | 0 | 집계 불가(요청 기록 없음) |
| padiem-b14 | active | 0 | 0 | 0 | 집계 불가(요청 기록 없음) |

- **#5479 재발: 없음**(NoGilError 0건) → PASS.
- **#6127 재발: 없음**(`/api/auth/status`·`/api/projects` 5xx 0건) → PASS.
- **closeable=YES** — §1의 종결 3조건 모두 충족.
- 종결 기준 밖 참고(그대로 인용): Chat 5xx 55건은 다른 라우트 — `/api/claw/*` 12,
  `/api/bookai/*` 11(공통 로그인 꺼짐 상태의 503 sync_unavailable, 11-01 20:35 전환으로
  해소 대상), `/api/pc/*` 11, `/api/chat/*` 9, `/api/orchestration` 6, `/auth/shared/*` 4
  (18:30 로그인 실패, #6561로 수정), `/api/connectors/*` 2. 11-01 배포·재시작 구간
  (17:25~20:04) 포함. **간헐 403은 별도 원인으로 확정·수정(#6563)** — #6127 판정과 무관.
- P01·B14의 "집계 불가(요청 기록 없음)"는 0이 아니라 접근 로그가 꺼져 있다는 뜻이다
  (README 규칙). Chat의 #6127 판정에는 영향을 주지 않는다.

## 5. 데이터 수집 경위 (이 세션의 사실)

- COM1(192.168.0.159)에서 COM2(K_lipvoice, 문서 기준 192.168.0.101)로 도달 불가:
  ping 100% 손실, `ssh -o BatchMode=yes` 포트 22 타임아웃(키·사용자 4종 시도,
  11-01 21:38~21:44 KST), 호스트명 미해석(NetBIOS·mDNS 모두).
- COM1에는 COM2용 SSH 키·설정이 없다(`~/.ssh`에 cgi_handoff 키뿐, known_hosts에
  192.168.0.101 없음, ssh-agent 미구동). 구버전 `scripts/ops/com2_remote_diagnose.py`
  의 설정 파일(`%USERPROFILE%\Padiem\com2-mesh-config.json`)도 COM1에 없다.
- GitHub에도 사전 리포트가 없었다(PR #6455 댓글 없음).
- 결론: 이 세션은 집계를 수행하지 못했고, **CTO가 컴2에서 직접 실행해 종결했다**
  (§0-1). 창이 닫힌 뒤에도 COM1→COM2의 읽기 전용 관측 경로는 여전히 없으므로,
  다음 관찰 과제가 있으면 컴2 레인 실행 또는 경로 신설이 먼저다.

## 6. 종결 절차 (완료)

1. COM2에서 §1의 명령을 실행(CTO, 읽기 전용) → `full_24h=YES`.
2. `closure` 값을 §4 표에 반영.
3. 배포 구간(§2, 17:25~20:04)의 5xx는 종결 기준 밖 참고로 분리 표기 —
   #6127 판정 라우트(`/api/auth/status`·`/api/projects`)는 그 구간 포함 전체에서 0건.
4. 결과를 #5479·#6127 이슈 댓글로 보고(완료: 2026-11-01T12:50Z)하고 이 문서로 근거화.
