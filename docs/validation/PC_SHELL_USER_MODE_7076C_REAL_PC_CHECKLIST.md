# pc_shell mode=user (7076c) 실기 검증 절차서 — 배포/설치 수행 금지

본 문서는 CTO 접근(1) 구현의 실기 검증 절차만 정의한다. 여기서는 설치/실행/배포를 수행하지 않는다.

## 전제
- PR #7076 머지본(`aa8e02af`, #7076 user helper pipe/framing/nonce/allowlist 계약) 기준.
- `PADIEM_MCP_PC_SHELL_ENABLED=true` 이고 `PADIEM_MCP_PC_SHELL_USER_MODE=true` 인 배포에서만 `pc_shell`/`pc_shell_start`의 `mode=user` 허용. 기본값은 OFF이며, OFF일 때 `mode=user`는 거부되고 기존(system) 경로는 변경되지 않는다.
- 실패 패스스루: helper/pipe 부재·연결 실패 → `user_session_unavailable`. helper 거부는 helper 오류코드 그대로. SYSTEM fallback 없음.
- 비밀값(credential/secret/token/키/쿠키/.env 값)은 출력/기록하지 않는다. 아래 명령의 `<DeviceId>`, `<SecretFile 경로>`는 경로/식별자 자리표시자이며 secret 값이 아니다.

## 컴1(helper) 설치/확인 순서
1. 대상 PC(컴1)에 #7076 이후 `apps/claw-connect` 코드가 배치된 상태에서, **로그인 사용자(limone) 세션**의 일반 권한 PowerShell로 사용자 로그온 작업을 등록한다(관리자 권한 불필요).
2. 이어서 **관리자 권한 PowerShell 1회**로 SYSTEM pipe ACL 부여 단계를 수행한다(install 스크립트의 `-GrantSystemAcl` 분기).
3. 사용자 로그온 후 helper가 실행 중인지 확인한다(작업 스케줄러 `\Padiem\PadiemUserSessionHelper`, ONLOGON, Limited). helper는 `--secret-file <SecretFile 경로>` 인자를 가진다. SYSTEM runcommand pipe-client는 이 작업 인자에서 secret 파일 경로를 발견해 nonce HMAC를 계산한다(명령문/dispatch/로그에 secret 값을 넣지 않음).

## 관리자 1줄 (DeviceId/SecretFile 경로만, secret 값 없음)
```powershell
.\install_user_helper.ps1 -DeviceId <DeviceId(dev_32hex)> -SecretFile <SecretFile 경로> -GrantSystemAcl
```
- 위 명령은 관리자 권한이 필요한 `-GrantSystemAcl` 단계를 포함한다. 등록 자체는 일반 권한 단계로도 가능(`-GrantSystemAcl` 제외).

## 확인 항목
1. **로그인 사용자 계정 확인**: 로그인된 사용자 세션에서 `whoami` 결과가 `limone`(또는 해당 PC의 대상 사용자)인지 확인.
2. **helper 중지/부재 시 실패 코드**: helper 작업을 중지하거나 사용자 로그오프 상태에서 `pc_shell mode=user` 요청 → 결과 오류코드가 `user_session_unavailable` 이고 SYSTEM fallback이 발생하지 않는지 확인.
3. **allowlist 밖 명령 거부**: `mode=user`로 helper의 shell 계약(stage-1 read-only, stage-2 powershell/cmd) 밖 명령 요청 → helper 거부 오류코드가 그대로 패스스루되고, SYSTEM에서 대신 실행되지 않는지 확인.

## 구현 메모(검증 관점)
- Chat MCP: `PADIEM_MCP_PC_SHELL_USER_MODE`(기본 OFF). OFF면 `mode=user` 거부, 기존 경로 불변. ON이면 `mode=user` dispatch에 `user_mode=true` 포함.
- oracle_mesh_dispatch: `user_mode` 컬럼(기본 0) + history create/select/poll 전달.
- kagent executor: `user_mode` command dispatch를 pipe-client PowerShell로 처리(`runcommand` 경유). PS는 작업 스케줄러 인자에서 `--secret-file` 경로를 찾아 #7076 framing(4-byte BE + UTF-8 JSON)과 nonce(HMAC-SHA256, `HelperRequest.material` 동일)를 사용. secret 값은 명령문/로그에 포함하지 않음. 연결 불가 → `user_session_unavailable`, helper 거부 코드 패스스루, SYSTEM fallback 없음.
- CI PS 실행: windows-latest의 `apps/claw-connect/tests/test_7105_stage2_windows_roundtrip.py`가 실제 PowerShell/cmd 자식과 named pipe를 왕복한다. framing/bytes 계약은 같은 시험의 golden 검증과 함께 고정한다.
