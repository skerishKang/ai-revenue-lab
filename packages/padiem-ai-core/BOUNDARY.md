# Padiem AI Core — Boundary & Ownership

> 문서 성격: **경계/명칭 정합성 문서** (이 PR은 기능 구현이 아님).
> 생성 위치: `packages/padiem-ai-core/BOUNDARY.md`

---

## 1. 권위 / 워크스페이스

- **실제 권위 저장소**: `skerishKang/ai-revenue-lab` (default branch: `main`). 모든 변경 권위는 이 저장소의 Git history / branch / commit / PR / issue로 귀속된다.
- **로컬 개발 워크스페이스**: `E:\padiem-ai-core` (git-bash `/e/padiem-ai-core`).
- 이 워크스페이스는 **별도 제품 저장소가 아니다.** `ai-revenue-lab` 내부의 Padiem AI Core 작업을 개발하기 위한 로컬 worktree / 작업공간일 뿐.
- **신규 GitHub repo는 생성하지 않는다.** Padiem AI Core는 `ai-revenue-lab` 내부의 기술 코어 계층이며, 별개 제품으로 재기획하지 않는다.

---

## 2. 정식 명칭 매핑 (canonical)

| 약어 | 경로 | 역할 |
|------|------|------|
| **B62** | `apps/padiem-chat` | Padiem Chat — 사용자 facing 채팅 UI / 설정 / 언어 / 테마 / 시네마틱 UX. Padiem AI Core의 reference client. |
| **Padiem AI Core** | `packages/padiem-ai-core` | 공유 모델 계약/런타임 레이어. `contracts.py`, `b14_*` 실행 경계, `execution`/`grounding`/`streaming`/`tool`/`web` runtime, `tests/`. |
| **B14** | `apps/korean-ai-platform` (+ `padiem_ai_core.b14_*` + `apps/padiem-ai-engine`) | Korean AI Platform — Korean-first 모델 접근 플랫폼. **Router Core / provider access / provider adapter / model execution의 단일 소유자.** |
| **B64** | `apps/ai-reward-router` | AI Reward Router — 별도 제품. Padiem AI Core 계약을 소비하는 클라이언트 중 하나 (**Padiem AI Core의 하류 아님**). |

> ⚠️ **명칭 정합성 고정**: 과거 프롬프트에서 쓰인 **"B14 AI Reward Router" 표현은 폐기**한다. 실제 reward router 제품은 **B64**(`apps/ai-reward-router`, `PRODUCT_CONTRACT.md`의 `Business: B64`)이며, B14는 Korean AI Platform(모델 실행 foundation)이다. 이슈/PR/문서 어디에도 reward router를 "B14"로 지칭하지 않는다.

---

## 3. 소유 경계 (ownership boundary)

```text
B62 Padiem Chat (apps/padiem-chat)
   └─ adapter (app/b14_client.py, transport only) ─▶ Padiem AI Core (packages/padiem-ai-core)
        ├─ contracts.py : Evidence / ToolSpec / AgentProfile / RunMetadata / ErrorClass
        ├─ b14_*.py     : B14 실행 transport 경계 (provider 선택 로직 없음)
        ├─ *_runtime.py : execution / grounding / streaming / tool / web (bounded, security 경계 포함)
        └─ tests/       : 모듈별 회귀 테스트
             │  server-side proxy (Cloudflare-neutral)
             ▼
   B14 Korean AI Platform (apps/korean-ai-platform)
      + Padiem AI Engine (apps/padiem-ai-engine)
        → provider access / Router Core / model execution = B14 권한 (단일 소유)

별도 제품: B64 AI Reward Router (apps/ai-reward-router) — Core 계약 소비자, Padiem AI Core 하류 아님
```

원칙 (출처: `packages/padiem-ai-core/README.md` 명시 소유 경계):

- **B14**가 provider access, Router Core, provider adapter, model execution을 소유한다.
- **B62**는 제품/reference client. 구체 provider/model을 주장하지 않는다 (`b14/auto` 위임, fail-closed; `model_policy.py` 참조).
- **Padiem AI Core**는 공유 계약/런타임만 제공한다. provider 선택·크레덴셜·retry·fallback은 B14 권한이다.
- **B64**는 Padiem AI Core와 독립된 제품으로, Core 계약을 소비할 뿐 Padiem AI Core의 하류 계층이 아니다.

---

## 4. 보안 / secret 원칙 (secret 미노출)

- provider secret(API key)은 **절대 frontend / B62 정적 자산**에 노출되지 않는다.
- Padiem AI Core는 server-side proxy / backend route로 provider 호출을 중계한다.
- B62는 provider를 몰라도 되는 client contract를 사용한다. B14는 provider 자체보다 routing decision contract를 담당한다.
- secret은 환경변수 / 배포 secret / 서버 런타임에서만 접근한다. `.env` 내용 출력, 로그 기록, 커밋을 금지한다.
- `apps/ai-reward-router/PRODUCT_CONTRACT.md`도 provider 크레덴셜은 server-side only, 커밋/진단 노출 금지로 명시한다.

---

## 5. production 변경 범위

- 이 문서는 **경계/명칭 정합성 문서**이다. 다음을 하지 않는다:
  - 기능 구현 / provider 호출 추가
  - API key 저장 / 출력 / 커밋
  - B62에 provider secret 추가
  - B14 ↔ B64 역할 혼합
  - production deploy
- Ready for Review 전환 / merge / production deploy는 사용자 승인 후에만 진행한다.

---

## 6. 기존 작업 참조 (중복 회피)

Padiem AI Core 경계는 이미 활발히 진행 중인 **Draft PR 트레인** 위에 세워져 있다. 본 문서는 재-scaffold가 아니라 **통합/참조** 목적이다.

- **Closed bootstrap 이슈**:
  - #927 — `[Padiem AI Core] Add opt-in Core-backed structured provider`
  - #934 — `[Padiem AI Engine] Slice 25 — internal language-neutral completed-run service boundary`
- **관련 Draft PR (일부)**:
  - #1140 `feat(b62): delegate Auto chat to B14 router` (#1100)
  - #1229 `docs: record B62 P01 B14 Control Plane ownership review`
  - #1218 `feat(core): add P01 adapter conformance harness`
  - #1192 `feat(engine): add trusted first-party service identity contract` (#1177)
  - #1159 `fix(b14): preserve unknown cost in route ranking` (#1102)
  - #1225 `feat(engine): integrate unified orchestration and approval lifecycle`
  - (전체 범위: **#1100~#1229** Draft PR 트레인)
- `packages/padiem-ai-core`는 이미 **v0.6.0**으로 존재 (`contracts.py` / `b14_*.py` / `*_runtime.py` / `tests/`). **신규 디렉터리 생성 없음.**

---

## 7. 이 PR의 허용 범위

- `packages/padiem-ai-core/BOUNDARY.md` 추가 (본 문서).
- README / AGENTS 등 타 문서는 저장소 자체에 명칭 drift가 없으므로 **변경하지 않는다** (최소 변경 원칙).
- 코드 기능 변경 없음. 기존 `packages/padiem-ai-core/tests/` 통과 유지.
