# Padiem Claw — Product Charter & PRD

## Product thesis

Padiem Claw는 사용자가 자연어로 맡긴 실제 디지털 작업을 **격리된 실행환경, 검증, 승인, 증거**를 통해 완료하는 Padiem의 대표 실행형 AI Agent 제품이다.

## Primary journey

```text
Connect/select repository
→ describe task
→ inspect context
→ plan
→ allocate local/cloud workspace
→ P01 orchestration
→ edit/run tests
→ show diff/evidence
→ request approval when required
→ result / Draft PR
```

## Product-owned scope

B54 owns task intent, repository/revision reference, product run projection, sandbox lease metadata, product-specific diff/test/PR artifacts and UX.

B54 does **not** own provider credentials/routing, reusable Agent/Tool/Skill/Memory/Evidence semantics, canonical account entitlements/credits, or B62 chat storage.

## Cloud target

- one task = one product run
- one cloud run = isolated sandbox lease
- sandbox allocation does not mean Agent started
- background execution supports durable status, cancel, resume and TTL
- GitHub output defaults to Draft PR
- parallel agents come only after single-run reliability

## User-facing language

- Product: **Padiem Claw**
- CTA: **Claw로 실행 / Run with Claw**
- Category: **Padiem Agents / Cloud AI Agent Workspace**
- URL candidate: `claw.padiem.net`

## MVP

```text
1 repository
1 task
1 isolated workspace
1 canonical P01 run
verified diff/test evidence
human-controlled write/PR boundary
no auto-merge
```
