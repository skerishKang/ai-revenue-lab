# ExLab Qwen3.8 Flash Next Uncensored — Owner correction, 2026-10-10

## Decision
The Owner selected this specific model for live evaluation during the currently free ExLab promotion and explicitly said data retention is not a blocker. The PR #3961 `model_data_policy_pending` and last-egress privacy refusals were unrequested and are removed in this correction. Do not reintroduce them.

## Fixed B14 registration
- B14 ID: `experiential/qwen3.8-flash-next-uncensored`; upstream ID: `qwen3.8-flash-next-uncensored`.
- Provider: Experiential Labs, `experiential`, origin `https://api.experientiallabs.ai/v1`, OpenAI Chat Completions.
- Credential binding name: `PADIEM_EXLAB_API_KEY`; actual secret value is never committed or logged.
- Catalog: 10 models / 7 providers; previous nine intact, retired B.AI Qwen and ExLab Luna remain excluded.
- Context 262144; advertised max output 65536, subject to B14 runtime request limits.
- Public ExLab catalog checked 2026-10-10 lists promotional input $0 / output $0 per million tokens. Price can change; confirm before benchmark.
- No auto selection, silent fallback, new tier membership or default model change. User selects explicitly.

## Validation
- Mock-based regression tests verify exact manual route and fixed origin/upstream, JSON and SSE provider dispatch, missing-secret fail-closed, and authentication/rate-limit response handling.
- Measured key availability, direct authenticated provider completion, synthetic Korean quote 10/10 evaluation and Production Worker activation are separate evidence gates. Do not claim that mock tests prove live operation.
- The Owner accepts the vendor data-retention tradeoff for evaluation; no additional retention-policy hold is authorized.

## References
- https://platform.experientiallabs.ai/models
- https://platform.experientiallabs.ai/docs/models
- https://api.experientiallabs.ai/api/models/qwen3.8-flash-next-uncensored
