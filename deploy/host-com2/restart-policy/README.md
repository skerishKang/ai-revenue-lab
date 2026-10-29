# COM2 자동 재시작 드롭인 (#4953 A)

장기 실행 COM2 서비스 8종이 어떤 이유로 죽어도 systemd가 다시 띄우도록 **드롭인 하나**를
설치한다. 유닛 원본 파일은 건드리지 않는다(드롭인은 `systemctl cat`에 병합되어 보인다).

```ini
[Unit]
StartLimitIntervalSec=0

[Service]
Restart=always
RestartSec=10
```

- `Restart=always` — 정상 종료(코드 0)와 실패 모두 재시작. 장기 서비스에는 이게 맞고,
  일회성 작업은 목록에 넣지 않는다.
- `RestartSec=10` — 즉시 재시작 폭주를 막는다(기존 유닛의 5초를 통일).
- `StartLimitIntervalSec=0` — 재시도 한도 없음(반복 실패도 journal에 계속 남긴다).

## 설치 (Qoder, dry-run 먼저)

```bash
./install.sh            # DRY_RUN: 유닛·대상 경로만 출력
sudo ./install.sh --apply
systemctl show -p Restart -p RestartUSec padiem-chat-com2.service   # Restart=always, 10s
```

- **시작·재시작·enable을 하지 않는다.** 드롭인은 해당 유닛의 다음 (재)시작부터 적용된다.
  지금 돌고 있는 프로세스 정책을 바꾸려면 그 유닛이 재시작될 때(또는 승인된 재부팅 때) 적용된다.
- `cloudflared.service`·`meshcentral.service` 이름이 호스트와 다르면 `SKIPPED_MISSING`으로
  보고된다 — `units.txt`에 실제 이름을 적고 다시 실행한다.
- 타이머·oneshot 유닛은 대상이 아니다(타이머는 스스로 반복, oneshot은 부팅 점검이 담당).
