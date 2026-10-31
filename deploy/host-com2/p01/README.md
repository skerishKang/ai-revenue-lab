# COM2 P01 Engine 꾸러미 (Linux/WSL, 127.0.0.1:8811)

상태: 꾸러미만 추가. **설치·기동·활성화 없음.** Windows `18731` 릴리스와 Tunnel은 건드리지 않는다.

CTO 결정(2026-10-31): P01 정본은 **Linux(WSL) systemd + 루프백 `8811`**. B14가 Linux `8789`로
정해진 것과 같은 근거다(COM2 운영 서비스가 이미 WSL/systemd에 있고, Windows 릴리스 프로세스는
로그온 세션·드라이브 마운트에 묶인다).

## 구성

| 파일 | 역할 |
| --- | --- |
| `padiem-p01.service.example` | systemd 유닛 템플릿. `--host 127.0.0.1 --port 8811` 고정 |
| `check_config.py` | `ExecCondition`·`start.sh`가 쓰는 설정 게이트. 이유 코드만 출력 |
| `health.py` | 루프백 `/internal/v1/health` 프로브. `scripts/ops/com2_runtime.py`의 `CONTRACTS["p01"]`와 같은 계약 |
| `start.sh` / `stop.sh` / `status.sh` | 기동·중지·읽기 전용 상태. `enable`은 하지 않는다 |
| `install.sh` | 기본 `--dry-run`. `--apply`로만 배치, `--reload`에서만 `daemon-reload` |
| `p01.env.example` | 이름만. 값은 호스트에서 채운다 |

## 설치·기동 (운영자가 실행)

```bash
bash deploy/host-com2/p01/install.sh              # 무엇을 할지 출력만
bash deploy/host-com2/p01/install.sh --apply      # 배치만. 시작·활성화 없음
bash deploy/host-com2/p01/start.sh
bash deploy/host-com2/p01/status.sh
bash deploy/host-com2/p01/stop.sh
```

`install.sh`는 `/opt/padiem/p01`이 이미 릴리스로 채워져 있는 것을 전제한다:
`/opt/padiem/p01/app/asgi.py`, `/opt/padiem/p01/venv/bin/python`. 없으면
`ASGI_ENTRY_MISSING` / `VENV_PYTHON_MISSING`으로 거부하고 아무것도 설치하지 않는다.

## 알려진 공백 — 엔진의 CPython ASGI 진입점

이 저장소의 엔진은 두 진입점만 있다: Cloudflare Worker(`apps/padiem-ai-engine/worker.py`)와
Windows 릴리스(`p01-ai-engine/start-p01-local.ps1`, 저장소 밖). 리눅스에서 8811로 띄울
**CPython ASGI 진입점(`asgi.py`)은 아직 저장소에 없다.** 그래서 이 유닛은 릴리스 디렉터리의
`asgi:app`을 실행하고, 파일이 없으면 `ConditionPathExists`·`check_config.py`가 먼저 거부한다.
없는 진입점을 이 꾸러미가 대신 만들어 내지 않는다 — 그건 별도 구현 레인이다.

## 경계

- Chat이 이 엔진을 부르는 주소는 Chat 호스트 설정이다:
  `PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN=http://127.0.0.1:8811` (설정 이름은 #6382).
  해당 `.env`는 `deploy/host-com2/chat` 소관이므로 이 꾸러미는 손대지 않고 여기 적어만 둔다.
- `8811`은 사용 중인 `8788`·`8789`·`8790`·`8797`·`8798`·`8801`·`8830`과 겹치지 않는다.
- 공개 노출 없음. Tunnel 매핑·DNS·Cloudflare 변경은 이 꾸러미의 권한 밖이다.

## 테스트

```bash
python -m pytest deploy/host-com2/p01/tests -q
```

유닛 렌더링(루프백·포트·`0.0.0.0` 부재), 스크립트 문법과 `systemctl start|enable` 부재,
설치 기본 dry-run, 설정 게이트 6종, health 계약이 `com2_runtime.CONTRACTS["p01"]`와 동일함,
환경 예시가 이름만 담는지 검사한다.
