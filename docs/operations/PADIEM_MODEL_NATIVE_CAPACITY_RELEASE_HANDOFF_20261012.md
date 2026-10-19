# PADIEM 모델 원생(Provider-native) 용량 정책 및 운영 인수인계 — 2026-10-12 KST

> 범위: `skerishKang/ai-revenue-lab`의 B14, B62 파디엠 챗, B66 견적, Claw/P01, B54 파디엠 엔진, shared Core.
> **판정:** 완료된 B62/B66 소스 수정은 이미 운영 반영. **엔진은 기존 정상 버전으로 복구돼 있으나 새 Core 릴리스 미반영**. 전체 제한 정비 **진행 중**, 통합 이슈 [#4379](https://github.com/skerishKang/ai-revenue-lab/issues/4379) **OPEN**.
> 이 문서는 시점 증적(스냅샷)이다. 이후 배포/PR이 일어나면 실제 served version을 다시 읽어 확인한다. 어떤 비밀값도 포함하지 않는다.

## 최신 운영 갱신 — 2026-10-12 KST (이전 스냅샷의 P0/P1 상태를 대체)

> 이 갱신은 아래 최초 인수인계 당시의 **미완료 목록**을 수정한 후속 증적입니다. 아래 3·4절의 과거 P0 shared Core / P1 B62 Chat 제한 상태는 이제 **완료된 이전 작업**이며, Claw·P01·B14·B54 작업은 계속 OPEN입니다. B54의 운영 롤백 버전을 덮어쓰지 않습니다.

| 제품 및 릴리스 | 정확한 소스/CI 증적 | 실제 운영 검증 | 현재 판정 |
| --- | --- | --- | --- |
| shared Core — B14 text/multimodal 및 ExecutionRuntime 기존 100/99 메시지, 개당 32,000자 제거 | [PR #4386](https://github.com/skerishKang/ai-revenue-lab/pull/4386), exact HEAD `d8b7e23965bb26f5fb863cbaa3fb21c511cd30ac`; [Core CI](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38162877176), [B62 CI](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38162877225), [Engine CI](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38162877250) 등 필수 6개 성공; 179개 focused + B66 안전 회귀 17개 PASS | B62 배포 번들에 포함; **Engine에는 배포하지 않음** | **Core 병합 및 B62 운영 반영 완료** |
| B62 독립 Chat 입력/히스토리 한도 20개, 8,000자/개, 총 32,000자 제거 | [PR #4388](https://github.com/skerishKang/ai-revenue-lab/pull/4388), exact HEAD `dee41e7383f704692e0a07739534c4250e98fbc0`; [B62 CI](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38163251626) + [브라우저 QA](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38163251707) 등 필수 7개 성공; focused 8개 PASS | [B62 읽기 전용 사전검사](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38163645648) 성공 및 [운영 배포](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38163713094) 성공 | **B62 운영 배포 완료** |
| B62 제공 버전 및 바인딩 | 배포 소스 `bebe7fc17b86d480c615ad97ff8353f0c3a2eba3` | 제공 버전 `d4f97dbf-7c34-495f-8721-bb8913944322`; `B62_BINDING_AUTHORITY_PRESERVED=PASS`, `SERVED_VERSION_SECRET_SET_EQUALITY=PASS`, 보존된 secret binding 10개, `B62_PRODUCTION_SMOKE=PASS`; 롤백 불필요 | **배포 및 안전 검증 완료** |
| B54 Engine | [#4383](https://github.com/skerishKang/ai-revenue-lab/issues/4383) | 지난 롤백 정상 버전 `4d90cf39-ca1b-48b4-977e-dce1ca576d7a` 유지. **이 갱신은 별도 신규 Engine served-version 재조회 증거는 아님** | **배포 금지 유지 / #4383 OPEN** |

**의도적으로 유지한 다른 성격의 한도:** B62 Chat 전송/메모리 안전 6,000,000바이트, Core 응답 바이트 및 이미지 파일 크기 가드, 엄격한 역할·요청 검증과 모델 선택/인증/승인/권한 경계, 저장 대화 미리보기 8,000자(긴 내용은 `[저장 미리보기: 전체 내용 중 일부만 저장되었습니다.]`로 명시). 이 저장 미리보기 제한은 모델에 보내는 원본 입력 제한이 아닙니다. 공급사 실제 최대 컨텍스트는 공급사별로 상이하므로 추정하지 않습니다.

**남은 범위:** Claw 일반 대화→P01 엔진 요청의 8,000자·64KiB / 수동 요청 4,000자와 40개 메시지 규칙, P01 모델 대기 300초와 승인/도구 실행 TTL 분리, Engine 모델 관련 HTTP 128KiB 요청 경계(단 #4383 해소 전 배포 금지), B14/동적 제공사의 streaming·응답 바이트·대기 정책, 파일·검색 문맥 요약/잘림. [통합 #4379](https://github.com/skerishKang/ai-revenue-lab/issues/4379)는 **OPEN**을 유지합니다.

**변경 관리:** 본 운영 문서만 추가 수정한 docs-only PR은 재배포를 발생시키지 않습니다.

---

## 1. 결정된 정책 — 모델 용량과 제품 권한을 혼동하지 않는다

1. 모델 **원본 입력 길이·출력 토큰·원본 답변 길이**를 과거 파일럿 수치로 전역 제한하지 않는다. 요청 파라미터를 생략하면 공급사 기본값을 유지하며, 명시값은 유효한 형식으로 전달한다. 공급사/중개사의 모델별 실제 한도를 *확인할 수 있으면* 참조하되 미상 값은 추정하지 않는다.
2. 공급사 응답 지연은 반드시 모델 처리 상한과 네트워크 연결·사용자 취소·작업 실행 경계로 나누어 판단한다. 단순히 타임아웃을 늘리는 것만으로 공급사 모델/복잡한 프롬프트 장애가 해결된다고 주장하지 않는다.
3. **반드시 유지**: 계정 인증·관리자 모델 OFF·요금/사용량 보호·소유자/테넌트 격리·P01 승인과 부작용 실행 제한·견적 품목/수량/금액 계산/타입 검증·문서 파일/압축/멀티모달 악용 방지·서버 메모리/전송 안전 한도·실제 연결 수명. 모델 성능 한도를 풀겠다고 승인·보안 가드를 삭제하지 않는다.
4. 안전 리소스 한도(HTTP request/response bytes)는 공급사 모델의 토큰 최대값이 아니다. 한도 때문에 거부한다면 분명하게 표기하고 필요 시 청크/스트리밍 등 안전한 설계를 검토한다. 브라우저/서버 양쪽 **조용한 자르기(truncation)**는 금지한다.
5. 단발 모델 호출에 대한 자동 외부 대체·재시도를 임의로 늘리지 않는다. 특히 무료 RPM과 명시적 모델 선택은 보호한다.

## 2. 검증 완료한 릴리스와 운영 상태

| 영역 | 검증된 변경/운영 | 증적 | 결론 |
| --- | --- | --- | --- |
| B66 사용자 AI 입력·모델 원본 응답·직접 공급사 대기 | 4,000자·24,000자 제한 해제, Kira/Experiential 직접 어댑터의 B66 고정 75초 제거; UI 잘림 방지 | [PR #4376](https://github.com/skerishKang/ai-revenue-lab/pull/4376), [B66 Pages 성공 38159326161](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38159326161) | **배포 완료**. 견적 스키마 및 응답 메모리 가드 유지 |
| B66 견적 AI 요청 숨은 ingress 제한 | `/api/b66/quote/interpret`만 기존 16KiB 공통 데이터 API 바디 상한에서 기존 `MAX_BROWSER_BODY_BYTES=6,000,000` 전송 안전 상한으로 분리. 관리자/메타데이터용 16KiB는 유지 | [PR #4378](https://github.com/skerishKang/ai-revenue-lab/pull/4378), [B62 Worker 성공 38160384205](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38160384205) | **배포 완료**. 테스트 63개 통과 |
| 공통 Core 전역 `max_tokens <=4096` | `B14ChatRequest` 및 output-budget 기본값에서 파일럿 전역 ceiling 제거. 명시적 양의 정수 전달; 선택적으로 설정한 *기능별* 출력 예산은 별도 판단 | [PR #4382](https://github.com/skerishKang/ai-revenue-lab/pull/4382), [B62 Worker 성공 38160781942](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38160781942) | **소스 병합 및 B62 배포 완료**. 111개 Core 집중 테스트 및 PR exact-head CI 통과 |
| B14 upstream | B14 Worker gateway는 이미 양의 `max_tokens`를 공급사에 위임하며, 정상적 SSE 읽기는 연결/청크 기반 정책 사용 | [통합 이슈 #4379](https://github.com/skerishKang/ai-revenue-lab/issues/4379) | 이번 변경분 B14 Worker 추가 배포 **불필요**. 실제 공급사 응답/1MiB 바디·600초 유휴 정책은 계속 감사 대상 |
| B54 파디엠 엔진 | 공유 Core 변경의 엔진 배포 명령이 성공했으나 served-version **기존 바인딩 6개 누락** 감지. 명시적 이전 버전으로 즉시 복구 | [실패 38160789452](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38160789452), [롤백 성공 38160918581](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38160918581), [차단 이슈 #4383](https://github.com/skerishKang/ai-revenue-lab/issues/4383) | **이전 검증 버전으로 복구; 신규 Core 배포 보류** |
| 현재 공개 UI / API | `https://chat.padiem.net/` 및 `https://quick-quote-kr.pages.dev/` GET HTTP 200 (단순 접근성 검사) | 2026-10-12 KST 읽기 전용 확인 | **사이트 접근 OK**. 실제 견적 모델 성공·회원 시나리오 전체 성공 증거는 아님 |

### 엔진 위험 대응 기록 (절대 CLOSED로 오인 금지)

- 배포 목표 main SHA: `b671193159510b7088aada55801ad145e165eb29`.
- 신규 배포 후 검출된 버전 `87ae6263-724e-479a-868a-598fe9bf0d01`; 검사 `B62_BINDING_AUTHORITY_PRESERVED=FAIL`, `removed_count=6`, `unexpected_added_count=0`.
- **복구 대상이자 최종 서빙 버전** `4d90cf39-ca1b-48b4-977e-dce1ca576d7a`; 공식 롤백에서 `POST_ROLLBACK_SERVED_EQUALS_TARGET=PASS`, `B54_ENGINE_PRODUCTION_ROLLBACK=PASS` 확인.
- 신규 엔진 배포 게이트를 다시 돌리거나 guard를 우회하지 말 것. 우선 기존/후속 immutable Worker 버전의 **바인딩 이름·타입만** 비교하고, 6개 바인딩 보존을 사전 조건으로 보강한 뒤 CI·검증·배포한다. DB 또는 비밀값 수동 변조 금지.

## 3. 아직 제거·조정되지 않은 모델 경로 제한 (이슈 OPEN 유지)

| 우선순위 | 담당 경로 | 지금 확인된 제품측 상한 | 안전한 후속 처리 |
| --- | --- | --- | --- |
| P0 | `packages/padiem-ai-core/padiem_ai_core/b14_execution.py`, `execution_runtime.py` | 요청 메시지 100개/개당 32,000자, 합성 시스템 컨텍스트 제한 | B14 upstream의 완화된 입력 정책과 맞추되 형식 검증·메모리 보호 유지. 긴 가상 메시지가 실제 provider adapter까지 무손실 전달되는 테스트 |
| P1 | `apps/padiem-chat/app/request_contract.py` | 챗 20개 메시지/개당 8,000자/총 32,000자 | browser+server+Core 모두 정렬. 히스토리 표시/저장 상한과 AI 모델 입력을 분리 |
| P1 | `apps/padiem-chat/app/claw_general_routes.py` 및 `claw_routes.py` | Claw 일반 8,000자/요청 64KiB, 일부 수동 intake 4,000자 | 승인된 사용자 요청 길이만 완화. P01 작업/도구/파일 명령의 권한·안전 예산과 분리 |
| P1 | `packages/padiem-ai-core/padiem_ai_core/contracts.py`, `p01_adapter.py` | ExecutionContext 300초 상한 | 공급사 AI 읽기 대기와 부작용 작업 실행·사용자 취소·approval TTL을 각각 분리 |
| P1 | `apps/padiem-ai-engine/app/service.py` | 엔진 execute 요청 본문 128KiB | 모델 원본 텍스트 ingress와 내부 tool/metadata 메모리 보호를 분리 |
| P2 | `apps/padiem-chat/app/documents.py`, `padiem_ai_core/grounding_runtime.py`, B66 파일 추출 | 첨부 문맥 2,800/2,600/8,000자 등, 문서 인식 경로 텍스트 32,000자 | 모델에 전달되는 내용의 임의 누락인지 vs 제품 검증 필드인지 구별, 누락 없이 용량 정책 표기 |
| P2 | B14/Core 네트워크·Worker | 기본 응답 바디 1MiB, 설정 가능 Core 응답 상한 최대 8MiB, read 유휴 watchdog 600초 | 모델 제한 아님. 실제 long-output 유스케이스를 측정해 스트리밍/응답 검증/안전 상한을 검토 |

**현재 확인된 코드 범위 내 주요 경로에 대한 감사이지, 모델 목록의 각 upstream 제공사 공식 토큰 수치를 전수 검증한 결과는 아니다.** 모델별 공식 문서나 레지스트리에 없는 capability 수치는 기입하지 않는다. 신뢰할 수 없는 무료 API 경로는 성공으로 표시하지 않는다.

## 4. 다음 담당자 체크리스트 / 변경 게이트

1. [ ] [#4383](https://github.com/skerishKang/ai-revenue-lab/issues/4383): 기존/불량 엔진 immutable served-version의 6개 바인딩 드리프트를 **읽기 전용**으로 확정, 재배포 전 보존 검사 구현. 엔진 신규 Core 코드 적용은 그 이후.
2. [ ] [#4379](https://github.com/skerishKang/ai-revenue-lab/issues/4379): shared Core 메시지 cap과 B62/Claw 입력/대화 문맥 cap을 **모델 원본과 제품 영속성 분리** 방식으로 작은 PR에서 수정. 숫자만 무작정 `None`으로 바꾸지 않는다.
3. [ ] P01/Engine 모델 대기 vs 명령 실행 timeout 분리. 사용자/파일 승인, exactly-once 실행 및 side-effect 안전 계약 보존.
4. [ ] 제품별 long-input/long-output **공급사 비호출 모의 테스트** 후 필요시에만 최소 실모델 테스트. Admin OFF 모델 호출 금지, 실제 고객 자료 사용 금지.
5. [ ] 정확한 PR HEAD CI GREEN + 실제 서빙 버전 readback + 기존 Cloudflare 바인딩 보존 + 필요한 런타임 smoke를 충족할 때만 배포/이슈 종료. 현 시점에서 #4379/#4383은 **OPEN**.
6. [x] B62/B66 모델 용량 개선이 이미 서빙된 사실을 확인했다. 단지 **문서의 main SHA가 달라졌다는 이유로** 같은 개선을 중복 배포하지 않는다. 그 이후 다른 담당자가 합친 신규 제품 코드(예: Claw UI [#4380](https://github.com/skerishKang/ai-revenue-lab/pull/4380))는 **별도 릴리스 필요성/서빙 버전 검사 대상**이며, 이 문서는 해당 변경의 운영 배포 완료를 증명하지 않는다.

## 5. 인계 링크

- 모델 한도 전 제품 감사: [#4379](https://github.com/skerishKang/ai-revenue-lab/issues/4379)
- 엔진 바인딩/운영 배포 차단: [#4383](https://github.com/skerishKang/ai-revenue-lab/issues/4383)
- B66 제한 해제: [#4376](https://github.com/skerishKang/ai-revenue-lab/pull/4376), [#4378](https://github.com/skerishKang/ai-revenue-lab/pull/4378)
- Core 4,096 토큰 해제: [#4382](https://github.com/skerishKang/ai-revenue-lab/pull/4382)
