# PC 연결을 더블클릭 한 번으로: `padiem-pc-connect.exe` (#5573, 2026-10-28)

```text
DOC_ROLE=PC_CONNECT_EXE_INSTALL_GUIDE
STATUS=IMPLEMENTED, 깨끗한 PC 1대에서의 실물 설치 증빙 미완료(빌드 호스트가 Windows 10 Home: Sandbox 없음)
ISSUE=#5573
CODE_SIGNING=NONE (대표 결정: 무서명으로 진행)
AGENT_INSTALL_OPTION=-install (measured on the tagged Windows agent, 2026-10-28)
AGENT_FOLDER=%ProgramFiles%\PADIEM
CONNECT_EXE_SHA256=a6700b9ff183147d6df8ebfa2cabf3aedd5ab440b2d8c43ac645c515822ca222
CONNECT_EXE_BYTES=34816
BUILD=scripts/pc_pairing/build-connect-exe.ps1
```

## 1. 왜 .exe로 바꿨는가

이전까지의 "원클릭"은 실제로 원클릭이 아니었다. 브라우저가 `padiem-pc-connect.ps1`을
내려주면 고객이 그 파일을 찾아 **우클릭 → PowerShell로 실행**을 골라야 했고, PowerShell
실행 정책이 걸리면 대화가 거기서 중단됐다. PC를 매일 쓰는 사람이 PowerShell을 모르면
그 순간 연결은 실패다.

`padiem-pc-connect.exe`는 같은 레인을 그대로 두고 **더블클릭 한 번**으로 만든다.

- 코드를 입력하지 않는다: 계정의 연결 표식(tag)이 파일 뒤에 붙어서 내려온다.
- 설치는 두 단계다: 에이전트를 내려받아 **`%ProgramFiles%\PADIEM\MeshAgent.exe`에 놓고**
  그 자리에서 `-install --agentName="tag [C D] PCNAME"`을 실행한 뒤 `-start`한다. 서버는
  그 이름을 관찰해 연결을 끝낸다.
  `-fullinstall`(에이전트를 program files로 복사하고 설치·실행한다고 적혀 있는 옵션)은
  2026-10-28 태그 빌드에서 exit 0만 내고 서비스를 아무것도 등록하지 않았다. 그래서 복사
  단계는 이 프로그램이 스스로 한다. `-install`은 **자신이 실행된 폴더를 서비스 기록에 남기
  는** 옵션이라, 임시 폴더에서 설치하면 그 폴더가 정리되는 순간 재시작 못 하는 서비스가
  된다(컴2의 현재 서비스 기록이 `D:\pdf1024\issue4317\tmpdocs\MeshAgent.exe`를 가리키는
  것이 바로 그 모양이다).
- 이미 설치된 PC에서 다시 실행하면 **같은 서비스 이름으로 갱신 설치**한다. 먼저 서비스
  기록의 ImagePath에 적힌 기존 바이너리로 `-stop`을 요구하고, 새 에이전트를 durable
  폴더에 놓은 뒤 같은 이름으로 `-install`·`-start`한다. 서비스는 `Mesh Agent` 하나이며
  중복 서비스는 만들지 않는다.
- 설치물이 남기는 것은 에이전트(`%ProgramFiles%\PADIEM\MeshAgent.exe`)와 제거 프로그램
  (`%ProgramFiles%\PADIEM\PadiemPcConnect.exe`), 그리고 Windows 앱 목록의
  `Padiem PC 연결` 등록이다. tag와 설치 링크는 프로세스 안에서만 살고, 내려받은
  임시 파일은 실행 직후 삭제된다.

## 2. 흐름

```text
웹 '내 PC 연결' 카드  →  POST /api/pc/pairings/install-exe  (로그인 세션, 코드 발급·소모 없음)
                     →  padiem-pc-connect.exe + PADIEMTAG/PADIEMURL 꼬리말  (Content-Disposition: attachment)
고객                  →  더블클릭
exe                   →  관리자 권한 요청 (거절하면 아무것도 하지 않고 종료)
                     →  이 PC의 로컬 드라이버 문자 수집 (네트워크 드라이브 제외)
                     →  "Mesh Agent" 서비스 감지 → 있으면 기존 바이너리로 -stop
                     →  https로만 에이전트 설치 프로그램 내려받기 (최소 TLS 1.2, redirect 재검사, MZ 확인)
                     →  %ProgramFiles%\PADIEM\MeshAgent.exe 로 복사
                     →  MeshAgent.exe -install --agentName="<tag> [C D] <PCNAME>", 이어서 -start
                     →  PadiemPcConnect.exe 복사 + Windows 앱 목록(PADIEM-PC-Connect) 등록
                     →  (선택) helper EXE를 versioned URL에서 내려받아 SHA-256 검증
                     →  %ProgramData%\Padiem\padiem-user-helper.exe + helper.secret(32바이트)
                     →  콘솔 로그인 사용자로 \Padiem\PadiemUserSessionHelper (ONLOGON, Limited) 등록·시작
                     →  helper-status.json 기록. 실패해도 위 연결은 성공으로 남는다
서버                  →  관찰된 이름에서 tag와 드라이버를 읽고 링크를 active로 만든다
```

카드의 기본 단추는 `.exe`이고, `설치 파일로 받기 (.ps1)`은 그대로 남아 있다. 사내 정책이
미서명 실행을 막는 PC에서는 같은 연결을 .ps1으로 끝낼 수 있다. `.exe`가
`pc_pairing_connect_exe_unavailable`로 거절될 때만 카드를 .ps1로 내려간다 — 로그인 실패
같은 거절을 몰래 다른 파일로 바꾸지는 않는다.

### 2.1 사용자 세션 helper (선택)

같은 원클릭 설치가 `padiem-user-helper.exe`도 provision한다. 이것은 서비스가 아니라
콘솔 사용자의 세션에서 도는 per-user 프로세스이고, 실패해도 MeshCentral 연결은 그대로
성공이다. helper가 없으면 서버는 기존 `user_session_unavailable`로 답할 뿐, PC 연결을
되돌리지 않는다.

```text
배포 설정  PC_USER_HELPER_INSTALL_URL=https://<static-host>/pc-helper/padiem-user-helper-7108.exe
          PC_USER_HELPER_SHA256=<그 빌드가 출력한 64-hex>
```

- **버전 고정 방식**: helper EXE는 agent와 같은 정적 배포 호스트의 **versioned path**로
  서빙하고, 배포가 URL과 SHA-256을 함께 고정한다. 빌드/배포 때 두 값을 같이 올리고,
  설치 파일과 .exe 꼬리말에는 그 두 값이 그대로 실린다. PC는 받은 바이트의 SHA-256이
  다르면 배치하지 않고 `sha256_mismatch`만 남긴다. 값이 없거나 잘못되면 helper 단계만
  생략되고 agent 설치는 정상 진행된다.
- 파일은 `%ProgramData%\Padiem\padiem-user-helper.exe`, 비밀은 같은 폴더의
  `helper.secret`(32 random bytes, 64 lowercase hex)이다. ACL은 `SYSTEM:(R)`과
  **콘솔 로그인 사용자** `:(M)`만 남기고 상속을 끊는다. 비밀값은 콘솔에도
  `helper-status.json`에도 쓰지 않는다.
- 작업은 `\Padiem\PadiemUserSessionHelper`, `ONLOGON`, `Interactive`, `Limited`이며
  등록 직후 시작한다. 사용자는 `Win32_ComputerSystem.UserName`에서 읽는다 — 설치가
  돌고 있는 관리자 승격 토큰이 아니라 실제로 그 PC에 로그인한 계정이다.
- `--device-id`에는 이 설치가 이미 가진 pairing tag(`pd-…`)를 넣는다. PR-3 executor는
  작업 인자에서 같은 값을 읽어 `padiem-user-helper-dev_<sha256 앞 32hex>` 파이프를
  계산한다. 즉 **설치 파일이 tag를 정하고, executor가 그 tag를 그대로 따라간다.**
- 결과는 `%ProgramData%\Padiem\helper-status.json`에 남는다. 성공은
  `{"status":"installed",…}`이고, 실패는 `download_failed`, `sha256_mismatch`,
  `no_console_user`, `secret_acl_failed`, `task_registration_failed` 중 하나와 함께
  `not_installed`로 기록된다.

## 3. 빌드와 재현

```powershell
Set-ExecutionPolicy -Scope Process Bypass
powershell -File scripts\pc_pairing\build-connect-exe.ps1
```

컴파일러는 Windows에 들어 있는 .NET Framework `csc.exe`(v4.0.30319)만 쓰고, SDK나 패키지
다운로드를 요구하지 않는다. 산출물은 Git에 **바이너리로 추적되지 않는다** — 실행 파일
자체가 아니라, 그 바이트를 base64으로 담고 같은 파일에 SHA-256을 박아 두는
`apps/padiem-chat/app/pc_pairing_connect_exe_asset.py`가 정본이다. Chat은 Cloudflare
Worker로 돌고, 코드와 함께 가는 바이트만이 반드시 서비스된다는 보장이 있기 때문이며,
이렇게 두면 리뷰어가 **물건과 지문을 한 화면에서** 본다.

`csc`는 빌드마다 랜덤 모듈 ID와 컴파일 타임 스탬프를 박아 넣기 때문에 같은 소스가 두 번
다른 해시를 내놓는다. `scripts/pc_pairing/connect-exe/win32_reproducible.py`가 둘을 소스
에서 파생된 값으로 갈아끼우고(PE 타임스탬프 0, GUID 휴지의 결정적 값), 빌드 스크립트는
**두 번 만들어 해시가 같지 않으면 산출물을 내지 않는다**.

```text
CONNECT_EXE_REPRODUCIBLE=1   # 두 번의 빌드가 같은 바이트
CONNECT_EXE_SEED=fc984d67eb1c3e936423c26eabc86cd9a74239acefdf3c378487e5a24f5e6342
```

`SEED`는 `PadiemPcConnect.cs`·`app.manifest`·`win32_reproducible.py` 세 파일의 해시에서
나오므로, 세 파일 중 하나라도 바뀌면 산출물 지문도 바뀐다.

위 블록의 `CONNECT_EXE_SHA256`, `CONNECT_EXE_BYTES`, `CONNECT_EXE_SEED` 세 줄은 빌드
스크립트가 이 파일에서 직접 갱신한다. 문서에 손으로 옮겨 적어 두고 잊는 사본이 되지
않도록, 테스트는 (1) 산출물 해시가 이 지문과 같은지, (2) 지금 이 소스 세 파일에서
나오는 시드가 기록된 시드와 같은지 확인한다. (2)가 없으면 "옛날 소스로 빌드된, 자기
로는 완전하게 정합적인" 산출물이 조용히 섞여 들어간다.

## 4. 서명이 없어서 뜨는 경고 — 무엇을 누를까

이 파일에는 **전자 서명이 없다.** 서명 구매는 대표 결정으로 미뤄졌고, 그래서 Windows는
첫 실행 때 경고 창을 띄운다. 그 경고는 오류가 아니라 안내다.

```text
Windows가 '알 수 없는 게시자' 경고를 띄우면
  [추가 정보]를 누른 뒤  [실행]을 선택하세요.
```

- 경고 창에는 파일 이름 대신 **제품 이름 `PADIEM`**이 표시된다. 서명이 없어도 파일에 적어
  둔 제품 이름·파일 설명·회사 이름은 그대로 보이므로, 이 설치 프로그램은 화면에서 항상
  `PADIEM PC 연결` / `PADIEM`으로 나온다.
- [추가 정보]를 눌러도 [실행] 버튼이 나타나지 않으면, 그 PC의 SmartScreen 정책(사내 그룹
  정책)이 미서명 실행을 완전히 막고 있다는 뜻이다. 그때는 카드의
  `설치 파일로 받기 (.ps1)`을 쓴다.
- 경고를 보다가 창을 닫아버려 파일이 실행되지 않은 경우: 다시 내려받아 실행하면 된다.
  내려받을 때 발급된 코드는 소모되지 않는다.

**스크린샷 자리** — 실제 경고 창은 깨끗한 Windows 1대에서 이 파일을 처음 더블클릭해 찍는다
(2026-10-28 현재 미첨부; 이 PC는 Windows 10 Home이라 Windows Sandbox가 없고 Hyper-V 관리
도구·Docker 데몬도 없다). 첨부할 화면 3장:

1. `padiem-pc-connect.exe` 더블클릭 직후의 "알 수 없는 게시자" 창 ([추가 정보] 누르기 전)
2. [추가 정보]를 눌렀을 때 [실행]이 나타난 창 (여기서 제품 이름 `PADIEM`이 함께 보인다)
3. 설치 후 `services.msc`의 `Mesh Agent`(실행 중/자동 시작) 또는 PADIEM '내 PC 연결' 목록에
   새로 붙은 PC 이름

## 5. 제거 방법

PC 쪽은 Windows 설정의 앱 목록에서 끝낸다. 설치는 `HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\PADIEM-PC-Connect`에 표시 이름 `Padiem PC 연결`, 게시자 `Padiem`, 버전, 제거 명령을 등록하고, 그 제거 명령이 실행할 프로그램을 `%ProgramFiles%\PADIEM\PadiemPcConnect.exe`로 복사한다.

```text
1) Windows 설정 > 앱 > 설치된 앱에서 "Padiem PC 연결" [제거]  (UAC 승인)
2) 또는 Padiem Connector 트레이 메뉴의 "Padiem PC 연결 제거 (관리자 승인)"
3) 제거 프로그램: MeshAgent.exe -fulluninstall (서비스 중지·등록 해제)
   → %ProgramFiles%\PADIEM 폴더 삭제 (프로세스 종료 후 cmd.exe가 수행)
   → HKLM ...\Uninstall\PADIEM-PC-Connect 등록 삭제
4) 서버 쪽 연결 해제는 웹 '내 PC 연결'의 [연결 끊기]로 한다.
   제거 프로그램은 웹 로그인 세션을 갖고 있지 않아 서버 해제를 대신 호출하지 않는다.
```

예전에 명령으로만 설치한 PC(앱 목록 미등록)는 관리자 권한 PowerShell에서:

```powershell
& "$env:ProgramFiles\PADIEM\MeshAgent.exe" -fulluninstall
Remove-Item -LiteralPath "$env:ProgramFiles\PADIEM" -Recurse -Force
Get-CimInstance Win32_Service -Filter "Name='Mesh Agent'" | Select-Object -ExpandProperty PathName
```

- 남는 것: 설치에 쓴 임시 파일은 실행 직후 삭제되므로 남지 않는다. 지운 뒤 남는 폴더도 없다.
- `.padiem-backup\<날짜>` 폴더는 PC 작업(쓰기/이동/삭제)이 만든 백업이지 이 설치물이 만든
  것이 아니다 — 설치 제거와 함께 지우지 않는다.
- 다시 붙이고 싶으면 같은 파일을 한 번 더 더블클릭하면 된다(갱신 설치).

## 6. 코드가 어디에 있는가

| 경로 | 역 |
|---|---|
| `scripts/pc_pairing/connect-exe/PadiemPcConnect.cs` | 프로그램 자체. 꼬리말 읽기, 권한 상승, 드라이버 수집, 기존 서비스 감지와 `-stop`, https 전용 내려받기, `%ProgramFiles%\PADIEM` 복사, `-install`·`-start`, 제거 프로그램 복사·Windows 앱 목록 등록·`-Uninstall` 제거 |
| `scripts/pc_pairing/connect-exe/app.manifest` | asInvoker + supportedOS (TLS 1.3 판단이 이 버전 인식을 읽는다) |
| `scripts/pc_pairing/connect-exe/win32_reproducible.py` | 재현 가능한 바이트와 PADIEM 버전 리소스를 손으로 쓰는 곳 |
| `scripts/pc_pairing/build-connect-exe.ps1` | 빌드·두 번 비교·지문 출력·자산 모듈 생성 |
| `apps/padiem-chat/app/pc_pairing_connect_exe_asset.py` | 검토된 바이트 + SHA-256 고정 (빌드가 생성) |
| `apps/padiem-chat/app/pc_device_pairing_routes.py` | `POST /api/pc/pairings/install-exe`, 꼬리말 작성 |
| `apps/padiem-chat/static/pc-pairing-card.js` | 기본 단추 = .exe, 보조 = .ps1, 무서명 안내 문구 |
| `apps/padiem-chat/tests/test_5573_pc_one_click_install.py` | 지문·꼬리말 거절·경로 동작·(Windows에서만) 실물 `--check` |

## 7. 확인한 것과 남은 것

### 2026-10-28 20:14 KST — 깨끗한 PC(CGI-1) 첫 설치 실패와 그 원인

- 목격: 경고 창 없이 실행돼 콘솔에 `이 PC에 에이전트가 아직 없고 서버가 설치 링크를 아직
  내려주지 않았습니다.`만 남았다. PC에는 `Mesh Agent` 서비스도
  `C:\Program Files\PADIEM`도 생기지 않았다.
- 원인은 한 줄이었다: 프로그램의 URL 검사자(`CleanHttps`)가 문자열 어디든 `@`가 있으면
  거부했다. 그런데 MeshCentral이 실제로 내주는 설치 링크는
  `https://mesh.padiem.net/meshagents?id=4&meshid=<노드>@<서버>`처럼 **쿼리에 `@`를
  담고 있다**(meshid가 노드 식별자이기 때문). 서버는 그 링크를 정상적으로 파일에
  적어 주었고, 프로그램이 그것을 버려서 "설치 링크 없음" 취급이 됐다.
- 왜 지금까지 몰랐나: 컴1·컴2는 에이전트가 이미 설치된 상태라 꼬리말 표식 → 설치 링크
  경로를 한 번도 타지 않았다. 첫 정 PC 시험이 처음 그 경로를 지났다.
- 고침: `@`는 **권한(authority) 자리에서만** 금지하고(사용자 이름/비밀번호 형태), 경로는
  통과시킨다 — 서버의 `install_url_from_config`가 이미 같은 규칙이고, 이제 둘이 같다.
  자격 증명이 들어간 링크(`https://evil@safe.example/…`)는 서버도 파일도 계속 거부한다
  (테스트로 고정). 표식이 있는데 링크를 못 읽는 경우는 `--check`가
  `CONNECT_EXE_CHECK=URL_UNUSABLE`로 구분해 알려 준다.
- 재현·검증: 실제 프로덕션 링크 형태로 `--check` → `CONNECT_EXE_CHECK=PASS`,
  `URL_PRESENT=1`, `--dry-run`이 `설치 대상 https://mesh.padiem.net/meshagents?id=4&meshid=…`를
  출력. 손으로 꼬리말을 바꿔 `user@host`를 만든 파일은 `URL_PRESENT=0` / `URL_UNUSABLE`.
- **재시도 방법: 새 파일이 필요하다.** 고친 곳은 exe 안이므로 바이트가 바뀌었다
  (아래 지문 참조). 기존 파일로 재시도하면 같은 메시지만 다시 나온다. 그 파일에 담긴
  표식(연결 코드에서 파생)은 10분이면 만료되니 어차피 재사용 대상이 아니다.

### 경고 창이 뜨지 않은 것(관측만 기록, 고치지 않음)

- CGI-1(Windows 11 Pro)의 첫 더블클릭에서 "알 수 없는 게시자" 창 없이 실행됐다.
  SmartScreen이 "알림만"또는 끄기 상태이거나, 브라우저가 파일을 보존하면서 영역 표기
  (Zone.Identifier)가 붙지 않았으면 경고는 뜨지 않는다. 즉 경고를 보는 PC도 있고 못 보는
  PC가 있다는 뜻이고, 안내 문구는 both 케이스에 대해 유효하다.

### 그 외

확인한 것:
- 두 번의 빌드가 같은 SHA-256을 냈다 (`CONNECT_EXE_REPRODUCIBLE=1`).
- 완성된 산출물의 `--check`가 이 PC(컴2)에서
  `CONNECT_EXE_CHECK_SERVICE_INSTALLED=1`, `CONNECT_EXE_CHECK_DRIVES=C D`,
  `CONNECT_EXE_CHECK_AGENT_TARGET=C:\Program Files\PADIEM\MeshAgent.exe`,
  `CONNECT_EXE_CHECK_SERVICE_PATH=D:\pdf1024\issue4317\tmpdocs\MeshAgent.exe`,
  `CONNECT_EXE_CHECK_TLS=1.2+1.3`을 출력했다 — 서비스 기록의 ImagePath를 읽어 기존
  바이너리를 알아 맞추는 경로가 실제로 작동한다는 증거다. `--dry-run`은
  `MeshAgent.exe -install --agentName="pd-… [C D] K_LIPVOICE"` 계획을 출력하고 아무것도
  실행하지 않았다.
- Windows가 읽는 파일 속성이 `PADIEM`(Company/Product), `PADIEM PC 연결`
  (FileDescription), `padiem-pc-connect.exe`(OriginalFilename)로 나온다.
- 서버가 쓴 꼬리말을 실제 exe가 다시 읽어 `pd-1234abcd [C D] K_LIPVOICE` 이름을 만들고,
  서버의 파서(`drives_from_agent_name`)가 `['C:', 'D:']`로 읽는다.
- 에이전트 자기 도움말에서 두 옵션의 정의를 읽었다(`-install` = "이 위치에서 서비스
  등록", `-fullinstall` = "program files로 복사 후 등록·실행"). `-fullinstall`이 아무
  서비스도 등록하지 않았다는 실측과, 이 PC의 서비스가 `-install`로 등록된 자리에 그대로
  붙어 있다는 사실이 같은 방향을 가리킨다.

남은 것:
- **깨끗한 Windows 1대에서의 실물 설치**: 다운로드 → "알 수 없는 게시자" 창 캡처 →
  [추가 정보] → [실행] → UAC → `Mesh Agent` 등록/실행 확인 → 웹에 이름으로 나타남 확인
  → 웹에서 연결 해제(서버 쪽 노드 기록은 별도로 정리). 2026-10-28 현재 이 PC는
  **Windows 10 Home**이라 Windows Sandbox가 없고(`Containers-DisposableClientVM` 없음),
  Hyper-V 관리 도구(`Get-VM`/vmms)와 Docker 데몬도 없다. 컴1·컴2는 시험 대상이 아니므로,
  깨끗한 Windows 1대(여분 노트북 또는 VM 호스트)가 잡히는 대로 이 절을 채운다.
- **`.ps1` 두 레인은 .exe와 같은 순서로 맞춰졌다(2026-10-28. 깨끗한 PC 실물 검증은 아직)**:
  `scripts/pc_pairing/install-padiem-pc.ps1`과 서버가 내려주는 자동 연결 스크립트 모두
  `-fullinstall`을 걷어내고 .exe와 같은 순서를 쓴다 — 기존 "Mesh Agent" 서비스를 서비스
  기록의 ImagePath 바이너리로 -stop → `%ProgramFiles%\PADIEM\MeshAgent.exe` 복사 → 같은
  서비스 이름으로 -install → -start → 서비스 상태 확인. 두 레인의 상수와 순서는 한 곳
  (`apps/padiem-chat/app/pc_pairing_agent_install.py`)에서 정의되고, 두 .ps1 사본이 같은
  블록을 담는지는 테스트가 강제한다. 깨끗한 PC 1대에서 두 경로가 실제로 서비스를 등록·
  기동하는지 확인하는 절은 그대로 남는다(지금까지 "이 PC 연결"이 확인된 PC는 에이전트가
  이미 붙어 있던 PC였다).
- 코드 서명을 사면: 바이트 뒤에 꼬리말을 붙이는 이 방식은 다시 봐야 한다(다운로드 시점에
  붙이면 서명 지문이 깨진다). 서명 이후에는 exe에 제품 주소만 구워 넣고 코드는 입력받는
  경로가 이미 남아 있으므로 그 경로가 본문이 된다.
