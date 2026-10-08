# StepFun Step 5 — B14 registration and 10 quote-implementation live trials (2026-10-09)

## Exact model registration

- Owner-authorized tenth manual model: kilo/stepfun/step-5-preview-free
- Upstream: stepfun/step-5-preview-free through the Kilo Gateway OpenAI-compatible API at https://api.kilo.ai/api/gateway.
- Local no-key verification before this run: direct HTTP 200, response model stepfun/step-5-preview. This establishes transport feasibility, **not persistent availability**.
- New canonical b14_models.json counts: 10 models / 7 provider registrations; Step 5 first in manual picker order for owner evaluation. Five previously deleted IDs stay absent.
- Kilo provider uses explicitly keyless credential mode. No new secrets, no automatic paid routing, no auto selection, no model group assignment, no Production deployment. Input/output unit prices recorded as UNKNOWN (null) rather than invented zero-price tariffs; free designation is a tested gateway path, not a customer Auto/free-first authorization.
- Runtime source guard also enforces the exact registered Kilo model/upstream tuple, blocking arbitrary Kilo requests by bypassing the manual model resolver.

## Quote implementation test protocol

- Ten **real B14 platform-adapter POST attempts**, one per case, sequential, one attempt per scenario, no model fallback or hidden retry. Test suite script: apps/korean-ai-platform/scripts/stepfun_quote_10case_probe.py.
- Generated prompts contain **synthetic items only**, no customer account details.
- Expected numeric quotes are deterministic. The final two tasks request safe printable A4 HTML and a Python quote calculator (with five deterministic local test cases).
- Evidence retained locally as E:/stepfun-quote-10-evidence-261009.json (ten bounded records). Raw model output absent because upstream rejected the requests.

| Trial | Quotation implementation objective | Actual provider result | Quality grade |
| --- | --- | --- | --- |
| 01 | Basic item multiplication, VAT | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 02 | Percentage discount, VAT, nontaxable shipping | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 03 | Fixed coupon before VAT | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 04 | Mixed taxable/exempt products | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 05 | Zero quantity / zero-price items | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 06 | Zero VAT + fixed discount | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 07 | Fractional VAT rounded to won | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 08 | Twelve line items + shipping | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 09 | A4 print HTML and escaping of injected customer name | HTTP 429 / KiloFreeRateLimited | Not assessable |
| 10 | Python quote calculator implementation + 5 local unit cases | HTTP 429 / KiloFreeRateLimited | Not assessable |

**Summary: 10/10 network requests attempted; 0/10 successful model responses. Not a 0% quote-quality score.** Provider-level 429 is sufficient to establish a serious current availability problem but does not prove StepFun's reasoning or code quality is poor. Earlier separate Kilo Code trials demonstrated one Python coding answer passing 8/8 unit cases and one Korean quote arithmetic error; not equivalent to this ten-case B14 trial.

## Release gate and next test

- The 10th route is source-registered in a **stacked Draft PR based on Draft PR #3819**. Neither branch is merged, and Production is untouched.
- This adapter may show credential readiness because Kilo explicitly permits anonymous gateway traffic, **but static readiness is not evidence that the overloaded free Step 5 endpoint can complete quotes**.
- Production quote/PDF readiness = **NO**, image-to-PDF parity / actual PDF generation = **NOT TESTED**. The B66 model_id-through-UI path is also a distinct outstanding integration.
- Do not top up, switch to paid Step 5, silently retry or auto-fallback. Re-run the 10 cases during demonstrably available free capacity with the owner-selected model, record exact responses and strict grades, then evaluate actual HTML/PDF fidelity against B66 reference output before a customer rollout.
