# PC read latency monitor (COM2 timer) — 2026-11-09

```text
DOC_ROLE=OPERATIONS_RUNBOOK
ISSUE_CONTEXT=pc_read 끝-끝 지연 감시(#6919 계승, #7232의 측정 도구)
SCOPE=자동 측정 타이머의 설치·동작·데이터·알림 규칙
```

## 무엇을 하는가

30분마다 CGI-1·컴1에 `pc_read` 1회씩을 **공개 `/api/mcp` 커넥터 계약 그대로** 보내
끝-끝 시간과 단계별 시간(identity·admission·큐 대기·pickup·guard·PC 읽기·
read_ok→submit·제출·응답 조립)을 JSONL에 쌓는다. 저널 마커(Chat 요청 이벤트,
`engine_timing`, `pc_queue_call`, `oracle-mesh-read/command phase=`, `pc_result`)로
회차를 대응한다. 회귀는 표로 보이고 추측으로 찾지 않는다.

## 구성 (컴2 WSL 기준)

| 역할 | 위치 |
|---|---|
| 측정 도구 | `/opt/padiem/pc-read-metrics/pc_read_measure.py` (본 저장소 `scripts/ops/pc_read_measure.py`) |
| 주기 실행 | `/opt/padiem/pc-read-metrics/run_cycle.sh` |
| systemd 유닛 | `/etc/systemd/system/padiem-pc-read-metrics.service` + `.timer` (`OnCalendar=*:00/30`, Persistent) |
| 결과 저장 | `/var/lib/padiem-pc-read-metrics/metrics.jsonl` — **최근 7일 보관**(기록 시각 기준 자동 정리) |
| 측정 토큰·경로 | `/opt/padiem/com2-secrets/pc-read-metrics/{cgi1.token,comp1.token,paths.json}` (600, 소유 root) |

토큰은 **발급·취급·배포 시에도 값을 출력하거나 커밋하지 않는다.** 설치 스크립트는
토큰 파일의 존재만 확인하고 값을 읽지·쓰지·띄우지 않는다. `paths.json`은 장치별
프로브 파일 경로(예: `{"cgi1":"C:/Windows/win.ini","comp1":"C:/Windows/win.ini"}`)만 담는다.

## 설치 (컴1에서, 저장소 체크아웃 기준)

1. 토큰·경로 파일을 먼저 준비한다(값은 별도 보호 채널로 전달):
   `sudo install -d -m 700 /opt/padiem/com2-secrets/pc-read-metrics` 후
   `cgi1.token`, `comp1.token`(각 MCP 토큰 값 1줄), `paths.json`을 600으로 둔다.
2. 저장소 스냅샷을 컴2로 옮겨 설치한다(`scp` 후 `wsl.exe -d Ubuntu -u root --exec bash`).
   ```bash
   bash deploy/host-com2/pc-read-metrics/install.sh
   ```
3. 확인: `systemctl list-timers padiem-pc-read-metrics.timer`, 첫 회차의
   `/var/lib/padiem-pc-read-metrics/metrics.jsonl` 마지막 행.

## 데이터 형식 (JSONL 한 줄 = 한 회차)

`ts`, `device`(cgi1|comp1), `label`(timer|manual), `http_status`, `call_status`,
`call_code`, `content_head20`(수신 파일 내용 앞 20자 — 수신 증거), `request_id`,
`elapsed_ms`, `stages{identity_ms, admission_ms, queue_wait_ms, pickup_ms,
guard_ms, pc_read_ms, read_to_submit_ms, submit_ms, chat_assemble_ms,
end_to_end_ms, run_hash, dispatch_id, slow_identity, files_calls}`.

- 비어 있는 단계(`null`)는 도달하지 못한 단계다(차단·실패). `call_code`가 그 이유다.
- 요약 조회: `python3 /opt/padiem/pc-read-metrics/pc_read_measure.py summarize [--since-hours N]`.

## 알림 규칙

한 회차가 **실패**(HTTP/도구 실패)하거나 **끝-끝 30초 초과**이면 도구는 stderr에
경고 한 줄을 남긴다(journal에 기록됨):

```
PC_READ_METRICS WARN device=cgi1 reason=failed|slow end_to_end_ms=...
```

유닛은 같은 회차에서 실패로 표시된다(시스템드 가시성용). 한 장치의 실패가 다른
장치의 측정을 막지 않도록 `run_cycle.sh`는 두 장치를 모두 시도한다.

## 유지보수

- 7일 보관은 기록 시 자동 정리다. 전체 수동 정리: `metrics.jsonl`에서 `ts_epoch`가
  7일보다 오래된 행을 지운다(도구의 `prune`과 같은 규칙).
- 토큰 교체: `cgi1.token`/`comp1.token` 내용만 보호 채널로 갱신(값 출력 금지).
- 중지: `systemctl disable --now padiem-pc-read-metrics.timer`.
- 원격 설치용 임시 파일(예: `/mnt/c/Users/<user>/pc-read-tmp`)은 설치 후 즉시 삭제한다.
