# PC 연결을 더블클릭 한 번으로: `padiem-pc-connect.exe` (#5573, 2026-10-28)

```text
DOC_ROLE=PC_CONNECT_EXE_INSTALL_GUIDE
STATUS=IMPLEMENTED, 실물 설치 증빙은 남은 PC 1대
ISSUE=#5573
CODE_SIGNING=NONE (대표 결정: 무서명으로 진행)
CONNECT_EXE_SHA256=6b0d84226f9b8a5f982d610ce8187cb82f7566b881b1ab990912800b3dc7f61a
CONNECT_EXE_BYTES=21504
BUILD=scripts/pc_pairing/build-connect-exe.ps1
```

## 1. 왜 .exe로 바꿨는가

이전까지의 "원클릭"은 실제로 원클릭이 아니었다. 브라우저가 `padiem-pc-connect.ps1`을
내려주면 고객이 그 파일을 찾아 **우클릭 → PowerShell로 실행**을 골라야 했고, PowerShell
실행 정책이 걸리면 대화가 거기서 중단됐다. PC를 매일 쓰는 사람이 PowerShell을 모르면
그 순간 연결은 실패다.

`padiem-pc-connect.exe`는 같은 레인을 그대로 두고 **더블클릭 한 번**으로 만든다.

- 코드를 입력하지 않는다: 계정의 연결 표식(tag)이 파일 뒤에 붙어서 내려온다.
- 설치는 이전과 완전히 같은 경로다: 에이전트를 내려받아
  `-fullinstall --agentName="tag [C D] PCNAME"`으로 실행하고, 서버가 그 이름을 관찰해
  연결을 끝낸다.
- 이미 설치된 PC에서 다시 실행하면 **같은 서비스 이름으로 갱신 설치**한다. 서비스는
  `Mesh Agent` 하나이며 중복 서비스는 만들지 않는다.
- 아무것도 디스크에 남기지 않는다: tag와 설치 링크는 프로세스 안에서만 살고, 에이전트
  설치에 쓴 임시 파일은 실행 직후 삭제된다.

## 2. 흐름

```text
웹 '내 PC 연결' 카드  →  POST /api/pc/pairings/install-exe  (로그인 세션, 코드 발급·소모 없음)
                     →  padiem-pc-connect.exe + PADIEMTAG/PADIEMURL 꼬리말  (Content-Disposition: attachment)
고객                  →  더블클릭
exe                   →  관리자 권한 요청 (거절하면 아무것도 하지 않고 종료)
                     →  이 PC의 로컬 드라이버 문자 수집 (네트워크 드라이브 제외)
                     →  "Mesh Agent" 서비스 감지 → 있으면 갱신, 없으면 신규
                     →  https로만 에이전트 설치 프로그램 내려받기 (최소 TLS 1.2, redirect 재검사, MZ 확인)
                     →  MeshAgent.exe -fullinstall --agentName="<tag> [C D] <PCNAME>"
서버                  →  관찰된 이름에서 tag와 드라이버를 읽고 링크를 active로 만든다
```

카드의 기본 단추는 `.exe`이고, `설치 파일로 받기 (.ps1)`은 그대로 남아 있다. 사내 정책이
미서명 실행을 막는 PC에서는 같은 연결을 .ps1으로 끝낼 수 있다. `.exe`가
`pc_pairing_connect_exe_unavailable`로 거절될 때만 카드를 .ps1로 내려간다 — 로그인 실패
같은 거절을 몰래 다른 파일로 바꾸지는 않는다.

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
CONNECT_EXE_SEED=c1d0148f707967908cd8ba95503d503a9973e425d510e2db6758dd40ef2541fa
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

**스크린샷 자리** — 실제 경고 창은 이 파일을 처음 더블클릭하는 PC 1대에서 찍어 넣는다
(2026-10-28 현재 이미지는 아직 첨부되지 않았다). 첨부할 화면 2장:

1. `padiem-pc-connect.exe` 더블클릭 직후의 "알 수 없는 게시자" 창 ([추가 정보] 누르기 전)
2. [추가 정보]를 눌렀을 때 [실행]이 나타난 창

## 5. 제거 방법

PC 쪽은 Windows 표준 경로로 끝낸다. 웹에서 연결을 해제하면 서버 쪽 권한이 사라지고,
PC에서 서비스를 지우면 에이전트가 사라진다.

```powershell
# 1) PADIEM 웹 '내 PC 연결'에서 해당 PC [연결 해제]  (폴더 승인도 함께 사라진다)
# 2) PC에서 에이전트 제거
& "${env:ProgramFiles(x86)}\Mesh Services\MeshAgent.exe" -uninstall
```

- 남는 것: 설치에 쓴 임시 파일은 실행 직후 삭제되므로 남지 않는다.
- `.padiem-backup\<날짜>` 폴더는 PC 작업(쓰기/이동/삭제)이 만든 백업이지 이 설치물이 만든
  것이 아니다 — 설치 제거와 함께 지우지 않는다.
- 다시 붙이고 싶으면 같은 파일을 한 번 더 더블클릭하면 된다(갱신 설치).

## 6. 코드가 어디에 있는가

| 경로 | 역 |
|---|---|
| `scripts/pc_pairing/connect-exe/PadiemPcConnect.cs` | 프로그램 자체. 꼬리말 읽기, 권한 상승, 드라이버 수집, 기존 서비스 감지, https 전용 내려받기, 설치 실행 |
| `scripts/pc_pairing/connect-exe/app.manifest` | asInvoker + supportedOS (TLS 1.3 판단이 이 버전 인식을 읽는다) |
| `scripts/pc_pairing/connect-exe/win32_reproducible.py` | 재현 가능한 바이트와 PADIEM 버전 리소스를 손으로 쓰는 곳 |
| `scripts/pc_pairing/build-connect-exe.ps1` | 빌드·두 번 비교·지문 출력·자산 모듈 생성 |
| `apps/padiem-chat/app/pc_pairing_connect_exe_asset.py` | 검토된 바이트 + SHA-256 고정 (빌드가 생성) |
| `apps/padiem-chat/app/pc_device_pairing_routes.py` | `POST /api/pc/pairings/install-exe`, 꼬리말 작성 |
| `apps/padiem-chat/static/pc-pairing-card.js` | 기본 단추 = .exe, 보조 = .ps1, 무서명 안내 문구 |
| `apps/padiem-chat/tests/test_5573_pc_one_click_install.py` | 지문·꼬리말 거절·경로 동작·(Windows에서만) 실물 `--check` |

## 7. 확인한 것과 남은 것

확인한 것:
- 두 번의 빌드가 같은 SHA-256을 냈다 (`CONNECT_EXE_REPRODUCIBLE=1`).
- 완성된 산출물의 `--check`가 이 PC(컴2)에서
  `CONNECT_EXE_CHECK_SERVICE_INSTALLED=1`, `CONNECT_EXE_CHECK_DRIVES=C D`,
  `CONNECT_EXE_CHECK_TLS=1.2+1.3`을 출력했고, `--dry-run`은
  "같은 서비스 이름으로 갱신 설치합니다"를 출력하고 설치는 실행하지 않았다.
- Windows가 읽는 파일 속성이 `PADIEM`(Company/Product), `PADIEM PC 연결`
  (FileDescription), `padiem-pc-connect.exe`(OriginalFilename)로 나온다.
- 서버가 쓴 꼬리말을 실제 exe가 다시 읽어 `pd-1234abcd [C D] K_LIPVOICE` 이름을 만들고,
  서버의 파서(`drives_from_agent_name`)가 `['C:', 'D:']`로 읽는다.

남은 것:
- **실물 설치 1회**: 빈 PC(또는 기존 에이전트를 갱신하는 실제 클릭)에서 더블클릭 →
  UAC → 설치 → 서버 확인. 무서명 경고 스크린샷도 이때 함께 얻는다.
- 코드 서명을 사면: 바이트 뒤에 꼬리말을 붙이는 이 방식은 다시 봐야 한다(다운로드 시점에
  붙이면 서명 지문이 깨진다). 서명 이후에는 exe에 제품 주소만 구워 넣고 코드는 입력받는
  경로가 이미 남아 있으므로 그 경로가 본문이 된다.
