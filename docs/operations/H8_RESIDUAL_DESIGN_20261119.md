# H8 잔여 설계 (2026-11-19 재작성)

원 설계 문서는 로컬 작업 폴더 정리로 사라졌고, 잔여 항목은 #7649·#7650으로 이슈화된 상태였다(#7464 대조 갱신, #8010 ④). 이 문서는 공개 저장소에 남길 설계만 다시 모은 것이다. 사고·배포·점검 기록과 PC 설치 상세는 비공개 운영 기록 위치에 두고 여기서는 경로를 적지 않는다.

## 목적

H8은 두 갈래였다. 하나는 Chat 코드 분리 수렴(T3)이고, 다른 하나는 이미 들어간 코드의 잔여 결함 정리다. 후자의 남은 설계가 계정 탈퇴의 미완 정리(#7649)와 PC 실행기·도우미 사이의 파이프 신원 전제(#7650)였다. 이 문서는 두 갈래의 지금 상태를 파일·줄 근거로 고정하고, 남은 단계와 대표·CTO 몫의 결정을 분리해 적는다.

## 지금 상태 (파일:줄 근거)

### 계정 탈퇴 미완 정리 — #7649, PR #7748 머지

마지막 연결 해제가 공통 계정 삭제를 보고했는데 준비 번호가 없으면 예전에는 503으로 끝나고 미완 기록이 남지 않았다. 지금은 요청 응답이 접수 상태로 돌아오고, 공유 마무리 대기 항목이 정리 대기열에 남아 재시도 경로가 집는다.

- `apps/padiem-chat/app/account_deletion.py:274-288` — `shared_account_finish`와 정리 포트 연결(공유 마무리 재시도 진입점).
- `apps/padiem-chat/app/account_deletion.py:12-13` — 정리 대상을 삭제 배치 안에 넣고 같은 배치 직후 drain하는 구조(#7557).
- `apps/padiem-chat/app/account_cleanup_pending.py:64` — `KIND_SHARED_ACCOUNT_COMPLETE`, `:242-248` — `pending_insert_statements`의 `ON CONFLICT(item_id) DO NOTHING`로 같은 계정 중복 기록 방지, `:348-425` — drain 경로.
- `apps/padiem-chat/app/expired_purge.py:268-276` — `shared_account_finish_for_secret` 연결, `:285` — 정리 대기 drain(요청 시점에 못 끝낸 항목의 매일 재시도).
- `apps/padiem-chat/tests/test_7649_unprepared_shared_complete.py` — 준비 번호 없는 공통 삭제가 접수 응답·단일 대기 행·재시도 완료로 전이되는 상태 단언.

### 파이프 흉내 수준 — #7650, PR #7781 머지

실행기가 도우미 명명 파이프에 연결할 때 흉내 수준을 지정하지 않으면 서버 기본값에 맡겨진다. 도우미는 접속자 토큰을 Identification 수준으로 조회하는 전제로 동작하므로, 클라이언트가 Identification을 명시해야 한다.

- `apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py:1727` — 5인자 `NamedPipeClientStream` 생성자로 `TokenImpersonationLevel.Identification` 명시.
- `apps/claw-connect/claw_connect/user_session_delegation.py:75-79` — `CreateFileW`에 `SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION` 명시.
- `apps/claw-connect/claw_connect/user_helper_peer.py:139` — 토큰 흉내 수준이 Identification이 아니면 본문 처리 전 `peer_impersonation_level_unexpected`로 거부. 기존 시스템 신원 확인은 그 뒤에 그대로 동작.
- `apps/claw-connect/tests/test_7650_pipe_identification.py`, `apps/korean-ai-code-agent/tests/test_7076c_user_mode_executor.py` — 채택 값 단언.

근거 기록의 결론: 3인자 생성자는 수준을 전달하지 않아 서버 기본값(수준 2)으로 관측되고, 명시 Identification 연결은 수준 1로 관측된다. 기본값이 전제와 맞지 않아 명시를 채택했다. 상세 분석과 실측은 비공개 운영 기록에 있다.

### 코드 분리 수렴 — #7813 종료

- `docs/operations/CHAT_HISTORY_MODULE_MAP_20261116.md:243-264` — `history.py` 661줄 → 237줄, 상한 337줄, 목표 300줄 이하 달성. 남은 6개 보조 메서드는 재수출 경로가 고정되어 있어 추가 분리 이득이 없고, 추가 분리 PR 없이 T3를 마감하는 제안을 남김. #7813은 종료됐다.

## 남은 단계

1. **PC 도우미 재설치 (#7564, 열림).** 코드 조각(#7637·#7641·#7643·#7676)과 흉내 수준 명시(#7781)는 모두 머지됐다. 실행기와 커넥터 배포도 운영에 반영됐다. 남은 것은 도우미 재설치와 그 뒤 동작 확인·관찰이다.
2. **배포 순서 유지.** 실행기(Identification 클라이언트)를 먼저, 도우미(Identification 외 수준 거부)를 나중에 재설치한다. 순서가 바뀌면 옛 실행기의 기본 연결이 새 도우미에서 거부되어 PC 사용자 모드 명령이 막힌다.
3. **재설치 뒤 30분 관찰.** 설치 폴더 잠금과 실행 경로 확인, 관찰 결과 기록. 이 관찰은 재설치 이후로 연기돼 있다.

## 열린 결정 (대표·CTO 몫)

| 결정 | 몫 | 현재 상태 |
|---|---|---|
| 도우미 재설치 실행 | 대표 | 소유자 세션에서 연결 코드 발급과 관리자 승인이 필요하다. 작업 세션은 설치 디렉터리·설정·페어링 파일을 바꾸지 않고 멈춰 있다. |
| 도달 불가 PC 네트워크 복구 | 대표 | 등록 PC 중 한 대가 도달 불가다. 복구 뒤 재설치 순서에 넣는다. |
| #7564 종료 시점 | CTO | 재설치와 30분 관찰이 끝난 뒤 닫는다. 이슈는 CTO가 닫는다. |
| #7649·#7650 후속 | 결정 불필요 | 두 이슈는 코드·시험 머지로 종료됐다. |

고객 대상 제한이나 새 승인 단계를 이 문서에서 만들지 않는다. 위 표는 이미 등록된 이슈와 배포 순서 결정(#7650 댓글, #7564 진행 결과)을 정리한 것이다.

## 범위 밖

- 계정·토큰·연결 코드 값, 사람 실명, 모델 이름은 이 문서에 적지 않는다.
- 비공개 운영 기록(권한 경계 상세, 배포·해시·점검 결과)은 공개 문서에 옮기지 않는다.
- 이 문서는 설계 상태 정리이며 배포·재설치를 실행하지 않는다.
