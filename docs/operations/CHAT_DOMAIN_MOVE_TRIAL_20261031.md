# Chat Custom Domain 이동 실측 계획

상태: **스크립트·시험·양식만 작성. 배포·Cloudflare 조회·변경·실측 미실행.**

이 절차는 `chat-cutover-test.padiem.net` 하나를 무해한 시험 Worker A에서 B로 옮기고, 별도 실행으로 A에 돌려놓는다. 운영 `chat.padiem.net`, `chat-com2.padiem.net`, tunnel, D1, 실제 Chat Worker는 대상이 아니다. 스크립트가 다른 hostname·Worker·zone을 거부한다.

## 1. 확인할 질문과 호출

| 질문 | 증거 |
| --- | --- |
| 기존 A 연결을 PUT 한 번으로 B로 바꿀 수 있는가 | PUT 시도 수 1, API 결과, 즉시·관찰 종료 후 소유 조회, HTTP fixture B 응답 |
| 응답이 끊기는가 | PUT 전부터 별도 스레드에서 수집한 HTTP 표본, 실패 수·상태·관측 시각·최대 표본 간격 |
| DNS/인증서 변화가 지연되는가 | baseline과 비교한 DNS 주소 집합·TLS leaf 인증서 SHA-256 및 첫 변화 관측 시각 |
| 되돌리기는 얼마나 걸리는가 | 별도 rollback 실행의 PUT 소요·즉시 소유 조회·첫 A 응답 시간 |

- 조회: `GET /accounts/{account_id}/workers/domains?hostname=chat-cutover-test.padiem.net`
- 이동·복귀: `PUT /accounts/{account_id}/workers/domains` (**Attach Worker Domain**).
- payload는 고정 hostname, 목표 service, 읽어서 대조한 zone ID, `enabled=true`, `previews_enabled=false`다. 삭제·재생성 폴백은 없다.
- 공식 API는 Attach를 정의하지만 이미 다른 Worker가 소유한 hostname의 단일 PUT 교체 동작을 명시적으로 보장하지 않는다. 이 시험의 목적이 그 부분의 실측이다.

근거: [Attach Worker Domain API](https://developers.cloudflare.com/api/resources/workers/subresources/domains/methods/update/), [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/), [Workers 권한](https://developers.cloudflare.com/workers/authorization/workers/).

## 2. CTO가 별도로 승인할 준비 작업

1. 계정은 기존 `Charliekant`다. 저장소의 계정 pin과 기존 `CLOUDFLARE_ACCOUNT_ID`를 대조한다. 토큰은 환경변수 `CLOUDFLARE_API_TOKEN`만 이용하며 출력하지 않는다.
2. 시험 Worker 이름은 `padiem-chat-cutover-trial-a` / `padiem-chat-cutover-trial-b`로 고정한다. `deploy/host-com2/chat-cutover-trial/worker.mjs`는 GET `/__cutover_trial`에 `A` 또는 `B`만 반환한다. 저장소·서비스 바인딩·upstream fetch·쓰기 경로가 없다. 다른 경로와 메서드는 404다.
3. 두 Worker 최초 배포와 test domain을 A에 최초 부착하는 작업은 이 스크립트에 없다. 승인받은 실행 레인이 별도 수행한다. 배포 예시는 아래와 같으며 **이 문서 작성 작업에서는 실행하지 않았다**.

```bash
npx --no-install wrangler deploy --config deploy/host-com2/chat-cutover-trial/worker-a.toml --keep-vars
npx --no-install wrangler deploy --config deploy/host-com2/chat-cutover-trial/worker-b.toml --keep-vars
```

4. 최초 연결은 API 또는 dashboard에서 test hostname → A로 한 번 설정하고 DNS/TLS가 정상화될 때까지 기다린다. 이 최초 발급 시간은 **이동 시간과 분리**해서 양식에 기록한다. 초기 domain이 없거나 현재 소유자가 예상과 다르면 시험 스크립트가 변경 전에 거부한다.
5. 기존 승인된 값으로 `CHAT_CUTOVER_TRIAL_ZONE_ID`를 설정한다. 스크립트는 조회 결과의 zone ID와 이름 `padiem.net`을 모두 대조하며 ID를 결과에 출력하지 않는다. `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`도 기존 인증 경로를 이용한다. 키 생성·회전·로그인 절차는 포함하지 않는다.
6. 실행 레인은 한 곳만 둔다. 이 API에는 소유자 compare-and-swap 계약이 없으므로 다른 운영자의 동시에 진행하는 수동 변경까지 원자적으로 차단할 수 없다. 중복 실행·다른 배포를 중지한 승인 창을 사용한다.

기존 Worker 이동 토큰에는 계정의 `Workers Scripts Write/Edit`(또는 Workers product Editor), `padiem.net` zone의 `Workers Routes Write/Edit`가 필요하다. **최초 Worker 생성** 권한은 별도이며 신규 roles에서는 Workers product Admin이다. 리소스별 현재 권한은 이번 작업에서 실측하지 않았다.

## 3. 읽기 전용 dry-run

`--execute`를 생략하면 기본 dry-run이며 `--dry-run`을 명시해도 같다. Git의 정확 main SHA, 계정 pin, 현재 domain 소유자, fixture HTTP, DNS, TLS를 읽고 변경 예정 내용을 결과 파일에 기록한다. PUT·Worker 배포·domain 최초 생성·DNS 변경은 하지 않는다. **로컬 계획 출력만 하는 모드는 아니며 외부 GET·DNS·TLS 조회를 한다.**

아래의 `$TRIAL_SHA`는 실행 직전 승인된 최신 main 40자리 SHA다. `git rev-parse HEAD`와 원격 main 모두 이 SHA여야 한다. 결과 디렉터리는 실행 레인이 미리 만들고, 기존 결과 파일은 덮어쓰지 않는다.

```bash
python .github/scripts/chat_domain_move_trial.py switch \
  --dry-run \
  --target-sha "$TRIAL_SHA" \
  --out /secure/evidence/chat-domain-switch-readonly.json
```

현재 소유자가 B일 때는 같은 명령에서 `switch` 대신 `rollback`을 쓴다.

## 4. 승인 후에만 수행할 이동과 복귀

승인된 실행 레인이 dry-run 결과를 확인한 뒤 switch를 한 번 수행한다.

```bash
python .github/scripts/chat_domain_move_trial.py switch \
  --target-sha "$TRIAL_SHA" \
  --execute \
  --confirmation "SWITCH_CHAT_DOMAIN_TRIAL_chat-cutover-test.padiem.net_${TRIAL_SHA}" \
  --observe-seconds 30 --interval-seconds 0.25 \
  --out /secure/evidence/chat-domain-switch.json
```

switch 프로세스 종료와 실제 B 소유를 읽기 조회로 확인한 뒤, **별도 실행**으로 rollback한다.

```bash
python .github/scripts/chat_domain_move_trial.py rollback \
  --target-sha "$TRIAL_SHA" \
  --execute \
  --confirmation "ROLLBACK_CHAT_DOMAIN_TRIAL_chat-cutover-test.padiem.net_${TRIAL_SHA}" \
  --observe-seconds 30 --interval-seconds 0.25 \
  --out /secure/evidence/chat-domain-rollback.json
```

각 실행의 PUT은 최대 한 번이다. PUT timeout·API 오류는 실제 적용 여부를 확정할 수 없어 `put_outcome=UNKNOWN`으로 남긴다. 읽기 관측과 소유 재조회는 이어가고 결과 파일을 보존한다. 자동 재시도·삭제·재생성·rollback은 하지 않는다. `UNKNOWN`, 예상하지 못한 소유, 응답 미수렴이면 CTO가 읽기 증거를 검토하기 전 변경 명령을 다시 실행하지 않는다.

종료코드 0은 `READ_ONLY_READY` 또는 `OBSERVED_TARGET`이다. 실패 표본이 있어도 최종 target에 도달하면 `OBSERVED_TARGET`일 수 있으므로 이 코드는 **무중단 승인**이 아니다. 운영 적용 판단에는 JSON 측정값과 아래 해석 한계를 함께 사용한다. 거부·불확실성·미수렴은 종료코드 2다.

## 5. 측정값의 뜻과 한계

- HTTP observer는 PUT 전에 첫 표본을 확보하고, PUT이 대기하는 동안에도 계속 돈다. DNS/TLS는 별도 스레드라 이 검사가 HTTP observer를 직접 막지 않는다.
- `first_target_response_seconds`는 PUT 시작부터 첫 target fixture 응답을 **관측한** 시간이다. rollback에서는 첫 A 응답으로 계산한다. `owner_immediate_readback_seconds`는 첫 소유 조회 완료까지, `put_seconds`는 API 왕복 시간이다.
- `http_failed_samples=0`은 기록된 해상도에서 실패를 관측하지 못했다는 뜻이다. 실제 단절 0초를 증명하지 않는다. `http_failure_observation_span_seconds`와 각 `recovery_bracket_seconds`는 표본 구간이며 지속 장애의 확정 길이가 아니다. 중간에 짧은 복구·장애가 있었을 수 있다.
- 요청 완료 시간과 DNS resolver 대기 때문에 실제 간격은 설정한 interval보다 길 수 있다. `http_sample_gap_max_seconds`와 개별 표본 start/end를 함께 본다. HTTP timeout은 재사용한 게이트의 30초, TLS connect timeout 기본은 5초이고 `--connect-timeout`으로 바꿀 수 있다. OS DNS resolver 자체 timeout은 시스템 설정을 따른다.
- `dns_first_observed_change_seconds=null`은 조회한 resolver에서 주소 변화가 없었다는 뜻이다. Custom Domain Worker 교체는 같은 Cloudflare 주소를 유지할 수 있다. 이 값은 authoritative DNS TTL·전체 지역 전파 지연이 아니다. TTL/지역 비교가 필요하면 실행 레인이 별도 DNS 자료를 양식에 첨부한다.
- TLS 표본은 leaf의 `certificate_not_before_utc`·`certificate_not_after_utc`와 `observed_utc`도 기록한다. `tls_first_observed_newer_not_before_seconds`는 baseline보다 늦은 notBefore를 처음 본 시간이다. notBefore는 인증서의 유효 시작일이며 CA 발급 이벤트 시각을 뜻하지 않는다. UTC 관측 시각과 `put_started_utc`·`put_ended_utc`를 이용해 아래 외부 기록과 대조한다.
- `tls_first_observed_certificate_change_seconds=null`은 같은 leaf fingerprint를 관측했다는 뜻이다. fingerprint가 바뀌어도 다른 edge 인증서일 수 있어 재발급을 증명하지 못한다. 스크립트는 항상 `certificate_reissuance=NOT_ESTABLISHED_BY_FINGERPRINT_SAMPLING`을 남긴다.
- 한 실행 위치·한 resolver·짧은 관찰 창의 결과를 전체 Cloudflare edge의 무중단 보장으로 확대하지 않는다. 실패 후에도 샘플·타이밍·소유 정보는 유지하며 응답 원문, 토큰, Authorization, 계정/zone ID는 기록하지 않는다.

### 5.1 승인된 실행 레인의 인증서 시각 대조 절차

1. **이동 전:** 기존 읽기 권한으로 Cloudflare dashboard의 해당 zone **SSL/TLS → Edge Certificates**를 확인하고, 노출된 certificate 상태·hostname·업로드/변경 시각을 관측 UTC와 함께 별도 기록한다. API로 읽을 때는 [List Certificate Packs](https://developers.cloudflare.com/api/resources/ssl/subresources/certificate_packs/methods/list/)의 `GET /zones/{zone_id}/ssl/certificate_packs`에서 해당 hostname을 포함하는 실제 항목을 먼저 찾는다. 응답에서 얻은 pack ID만 [Get Certificate Pack](https://developers.cloudflare.com/api/resources/ssl/subresources/certificate_packs/methods/get/)에 쓸 수 있다. **Workers domain의 `cert_id`가 certificate pack ID와 같다고 가정하지 않는다.** 관리 인증서가 이 목록에 반드시 노출된다고도 가정하지 않는다.
2. **이동 직후와 관찰 종료:** 같은 읽기 화면/API에서 상태와 실제 `certificates[].uploaded_on`·`modified_on` 값을 다시 기록한다. 공식 API의 `uploaded_on`은 Cloudflare 업로드 시각이고 `modified_on`은 변경 시각이다. 둘을 CA 발급 시각으로 바꾸어 부르지 않는다. API 원문에는 검증용 자료가 포함될 수 있으므로 통째로 보관하지 말고 필요한 상태·시각·대조 근거만 기록한다.
3. **발급 이벤트 확인:** 기존 조회 권한이 있으면 [Cloudflare Audit Logs](https://developers.cloudflare.com/fundamentals/account/account-security/audit-logs/)에서 위 이동 창과 관련 certificate/resource 이벤트를 확인하고, 실제 제공되는 action 종류·action timestamp와 근거 위치를 양식에 적는다. 이 로그에 해당 관리 인증서의 **발급 완료를 명시하는 이벤트**가 존재한다고 보장하지 않는다. 생성/업로드/수정 이벤트만 보이면 그 종류 그대로 기록하고 `issuance_event_utc=NOT_OBSERVABLE`로 둔다. 접근 권한이나 자료가 없으면 역시 그 사유를 기록하며 토큰 권한을 임의로 확대하지 않는다.
4. **TLS와 맞추기:** 스크립트의 `tls_first_success_after_put_utc`, `tls_first_observed_certificate_change_utc`, `tls_first_observed_newer_not_before_utc`를 별도로 기록한다. 실제 발급 이벤트와 서비스된 인증서의 연관을 확인할 수 있을 때만 발급 이벤트→첫 TLS 제공까지의 관측 지연을 계산한다. 연관이 불분명하거나 이벤트가 없으면 발급 지연은 `NOT_OBSERVABLE`, TLS 제공/전환 지연만 실측값으로 보고한다.
5. **복귀에서도 반복:** rollback 전·후 같은 기록을 따로 남긴다. 같은 인증서 재사용, 새 인증서 관측, 발급 여부 미확정을 구분한다. 추가 API/로그 조회는 이 시험 스크립트에 자동으로 포함하지 않았으며, 이미 승인된 읽기 경로로 실행 레인이 수행한다.

## 6. 결과 기록

기록 양식: `docs/operations/templates/CHAT_DOMAIN_MOVE_TRIAL_RESULT.json`.
양식을 복사해 실행자, 승인 근거, 위치, 최초 준비 시간, switch/rollback 결과 파일, 실제 판단을 채운다. `NOT_MEASURED`를 실제 관측값으로 대체하기 전에는 운영 검증 완료로 쓰지 않는다. 실측 JSON은 저장소 밖 승인된 증거 위치에 보관한다. 운영 전환 결정은 CTO가 내리며 이 시험이 자동으로 운영 게이트를 실행하지 않는다.
