# COM2 리허설 서명 증거 발행

상태: 코드·오프라인 시험만 완료. 리허설 실행, 키 생성, 저장소 밖 업로드, 환경 설정, 게이트 실행은 하지 않았다. #6419의 미확정 GitHub Actions 리허설 producer를 아래 경로로 대체한다.

## 1. 선택 비교

| 방식 | 필요한 구성 | 판단 |
| --- | --- | --- |
| (a) COM2가 서명한 요약 JSON을 외부 아티팩트로 발행 | 기존 COM2 Python + 전용 Ed25519 키 파일 + 승인된 HTTPS 객체 저장소 | **선택.** 게이트는 공개키만 갖고, COM2가 내려가도 이미 발행한 증거를 읽을 수 있다. 새 서비스·포트가 없다. |
| (b) COM2 `/internal`에서 서명 요약 조회 | 새 읽기 endpoint, ingress 인증·배포·가용성 관리 | 이번 범위에서는 추가 서버 구성이 필요하고, 전환 중 COM2 상태에 증거 조회도 의존한다. |
| (c) 수동 입력 또는 서명 없는 Actions artifact | operator 입력 또는 별도 producer workflow | COM2 발행자 서명을 증명하지 못한다. 서명한 파일을 Actions로 옮기는 방법은 가능하나 별도 workflow 없이 (a)의 HTTPS transport로 충분하다. |

암호 구현은 COM2 호스트가 이미 사용하는 `cryptography==46.0.7`의 Ed25519를 재사용한다. 직접 암호 알고리즘을 구현하지 않는다. [공식 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/).

## 2. 신뢰와 파일 계약

- 서명 키는 COM2의 저장소 밖 전용 PKCS8 PEM 파일이다. Chat 엣지 서명 키·로그인 키를 재사용하지 않는다. 이 도구는 키를 생성하거나 출력하지 않는다.
- 승인된 공개키 PEM을 GitHub `production` 변수 `CHAT_COM2_REHEARSAL_PUBLIC_KEY_PEM`에 고정한다. 파일의 키·algorithm·URL을 신뢰 근거로 사용하지 않는다. 키 교체는 CTO가 공개키 설정을 갱신하는 별도 작업이다.
- `CHAT_COM2_REHEARSAL_EVIDENCE_URL`에는 승인된 객체 저장소의 **정확한 HTTPS 읽기 URL**을 둔다. 예시 객체 경로는 `chat-rehearsal/<main_sha>/<generation_id>/evidence.json`이다. 쓰기용 presigned URL과 구분한다. 도메인/버킷을 이번 코드에서 신설하거나 임의로 정하지 않는다.
- 객체 읽기는 비밀이 없는 서명 요약만 대상으로 한다. 접근 제어가 필요한 저장소에서는 기존 인가 경로를 먼저 정해야 한다. 게이트는 URL redirect를 따라가거나 저장소 계정을 추측하지 않는다.
- 발행 도구의 선택적 업로드는 저장소 밖 파일에 보관된, 이미 승인된 HTTPS PUT URL을 읽는다. URL은 명령줄·로그에 출력하지 않고 redirect·자동 재시도를 하지 않는다. 객체 저장소와 URL 발급은 이 작업에서 실행하지 않았다.
- 서명은 schema 문맥과 canonical JSON 전체에 적용한다. payload에는 `COM2` 발행자, 대상 staging origin, main SHA, 세대 ID·원본 DB 해시, 원본 보고서 해시, 시작·종료·발행·만료 시각, 8단계 판정만 들어간다. DB 행·응답 원문·로컬 경로·명령·키·토큰을 넣지 않는다.
- 유효기간은 `.github/scripts/chat_rehearsal_evidence.py`의 `MAX_EVIDENCE_AGE_SECONDS = 86400`이다. 완료 시각부터 **24시간**, 경계에서 만료다. 늦게 재서명하거나 다시 업로드해도 유효기간이 늘어나지 않는다. 시각 순서 오류·미래 시각은 거부한다. 기간 변경은 코드 검토 대상이다.
- 저장소를 변조할 수 있어도 고정 공개키에 맞는 서명 없이는 통과하지 못한다. 이 증거의 신뢰 주체는 COM2 서명 키와 승인된 발행 코드다. COM2 또는 서명 키 자체가 침해된 상황까지 증명하는 장치는 아니다.

## 3. 사람이 수행할 발행 순서

기존 `chat_cutover_rehearsal.py`를 그대로 호출한다. 이미 만든 PASS 로그/JSON에 임의 세대와 SHA를 붙여 서명하는 기능은 없다. 기존 리허설의 쓰기 동결·정지 확인·스테이징 제한도 유지한다.

1. 승인된 최신 main을 깨끗한 COM2 checkout에 준비한다. 로컬 HEAD와 원격 main이 `REHEARSAL_SHA`와 일치해야 한다. tracked/untracked 변경이 있으면 거부한다. 출력·인자·키 파일은 모두 checkout 밖에 둔다.
2. 기존 절차의 인자를 저장소 밖 JSON 문자열 배열에 둔다. **데이터 파일/디렉터리 인자는 모두 절대경로**다. `--json`은 발행 도구가 관리하므로 넣지 않는다. `--synthetic`, `--dry-run`으로는 발행할 수 없다.

```json
[
  "--base-url", "https://chat-com2-staging.padiem.net",
  "--generation-pointer", "/approved/snapshots/current_generation.json",
  "--generations-dir", "/approved/snapshots/generations",
  "--snapshot-a", "/approved/rehearsal/baseline.sqlite3",
  "--snapshot-b", "/approved/rehearsal/window-end.sqlite3",
  "--staging-db", "/mnt/d/padiem/chat-staging/chat.sqlite3",
  "--sentinel", "/mnt/d/padiem/chat-staging/MAINTENANCE",
  "--mirror-inventory", "/approved/rehearsal/r2-inventory.json",
  "--confirm-stop-tick", "--confirm-stop-wss", "--confirm-stop-queue"
]
```

`/approved/...`는 실행 레인의 실제 승인 경로로 바꾼다. 기존 root 보호 규칙 때문에 새 staging DB를 root로 만들려면 소유자가 정해져야 한다. 서비스 계정으로 실행하거나 이미 소유권이 설정된 staging DB를 기존 절차에 따라 준비한다. 발행 도구가 이 보호장치를 해제하지 않는다.

3. 실제 세대 포인터의 ID를 `GENERATION_ID`에, 승인된 40자리 main SHA를 `REHEARSAL_SHA`에 둔다. 이미 준비된 키/공개키와 업로드 URL 파일을 지정한다. 다음은 승인 후 COM2 실행 레인이 쓸 명령이며 이번 작업에서 실행하지 않았다.

```bash
python .github/scripts/chat_publish_rehearsal.py \
  --args-file /approved/rehearsal/args.json \
  --main-sha "$REHEARSAL_SHA" --generation-id "$GENERATION_ID" \
  --key-file /approved/keys/rehearsal-private.pem \
  --public-key-file /approved/keys/rehearsal-public.pem \
  --out /approved/evidence/rehearsal-signed.json \
  --upload-url-file /approved/private/rehearsal-put-url.txt
```

`--upload-url-file`를 생략하면 서명 파일만 만든다. 기존 출력 파일은 덮어쓰지 않는다. 발행 도구는 아래를 수행한다.

1. 기존 staging 대상 검사, 정확 main·깨끗한 checkout, 기대 세대 ID와 원본 DB 해시 확인.
2. 선택한 세대 포인터를 임시 사본으로 고정해 child에 전달. 원래 포인터가 A→B→A로 움직여도 child는 고정 A를 쓴다.
3. 기존 리허설을 실제 호출. 종료코드 0과 `REHEARSAL_SUMMARY=PASS stages=8 passed=8 ...` 및 8단계 JSON 모두 확인. `--apply-pending`의 기존 reflect 패리티 대체만 인정한다.
4. 실행 후 main/checkout·현재 세대·원본 DB 해시 재확인. 바뀌었으면 발행하지 않는다.
5. 최소 요약을 서명하고, 지정 공개키로 자체 검증한 뒤 저장소 밖 파일에 배타적으로 저장. 원본 보고서·포인터 임시 사본은 정리한다. 지정했다면 HTTPS PUT으로 요약만 업로드한다.

업로드만 실패하면 이미 서명된 결과를 다시 검증해 업로드할 수 있다. 리허설을 재실행하거나 만료를 갱신하지 않는다.

```bash
python .github/scripts/chat_publish_rehearsal.py \
  --upload-existing /approved/evidence/rehearsal-signed.json \
  --main-sha "$REHEARSAL_SHA" --generation-id "$GENERATION_ID" \
  --public-key-file /approved/keys/rehearsal-public.pem \
  --upload-url-file /approved/private/rehearsal-put-url.txt
```

## 4. 게이트 연결

`chat-com2-cutover-gate.yml`의 수동 실행 입력은 `mode`, `target_sha`, `confirmation`, `generation_id`, 필요 시 `readonly_run_id`다. 기존 `rehearsal_run_id`, `CHAT_COM2_REHEARSAL_WORKFLOW`, `CHAT_COM2_REHEARSAL_MAX_AGE_HOURS`는 더 이상 사용하지 않는다.

- preflight/readonly/switch는 `generation_id` 필수. 입력한 main SHA와 세대가 서명된 요약과 각각 정확히 같아야 한다.
- 게이트는 설정된 URL에서 요약을 읽고 고정 공개키·schema/발행자·대상·서명·24시간·세대·SHA를 검증한다. 없다거나 불일치하면 실패한다. unsigned artifact/Actions 성공 상태로 대신 통과시키지 않는다.
- switch는 같은 SHA **및 세대**의 성공한 readonly 실행을 요구한다. run title도 `chat-com2/readonly/<sha>/<generation>`이다.
- 배포 후 PUT 직전에 증거를 다시 읽어 검증한다. 배포 중 만료되거나 다른 세대로 교체된 증거를 쓰지 않는다.
- rollback은 증거 저장소·서명 라이브러리 설치·COM2 가용성에 의존하지 않는다. 기존 main/확인문구/production/직렬화/legacy 동결 검사는 유지한다.

## 5. 확인 범위

오프라인 시험은 RFC 8032의 공개 시험 벡터로 서명/위조/만료/다른 세대·SHA·키를 확인한다. 시험 중 운영 키를 만들거나 읽지 않는다. 업로드·Cloudflare·리허설 실행 경계는 가짜 응답으로 대체한다. 실제 객체 저장소, 키 배치, production 변수 설정과 실제 COM2 발행은 CTO가 별도 지정한 실행 레인의 작업이다.
