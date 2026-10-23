# 5034 — Claw web alert inbox

Product gate: #5015 (alert inbox surfacing for Claw web UI).

## Status 2026-10-24

- 010 적용(run 40004007436) / D1Result 파싱 수정(#5669)·오류코드 분리(#5674)·010 preflight(#5682) 배포(run 40018238667, 75f631e0)
- mark-read·navigation은 첫 실제 알림 시 확인

## Notes

- `010` = alert-inbox feature slice gated under #5015.
- D1Result 파싱 및 오류코드 분리(#5669, #5674): alert dispatch D1 쿼리 응답 파싱을 강화하고, 오류를 코드별로 분리하여 030/040/050 등 단계별 진단이 가능하도록 수정.
- 010 preflight(#5682): Owner action 없이 실제 알림 흐름을 사전 검증(첫 실제 알림 도착 시 mark-read·navigation 동작 확인).
