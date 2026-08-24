# B60 2026-08-24 Official-Source Publish Record

Issue: #688

## Authority

The owner granted standing CTO approval on 2026-08-24. The CTO applies that authority only after evidence gates pass; a blocked source is rejected rather than force-approved.

## Promotion audit

- Canonical input main: `5e4625c89dc954a87ed245bba89a1ba822e596ec`
- Successful promotion audit run: `32702333835`
- Job: `97356256020`
- Review packet: `b60rp_bbc9abfd5761d4c518f3`
- Approved candidates: 6
- Rejected candidates: 1
- Rejected source: `google-gemini-pricing`
- Rejection reason: `NO_OBSERVATIONS` + `MISSING_REQUIRED:freeLabel`
- Verified changes: 1
- Reverified unchanged fields: 10

## Published semantic change

`cloudflare-workers-ai-free.price`

Before:

`10,000 neurons/day free`

After:

`10,000 neurons/day free; $0.011/1,000 above allocation`

Official source: `https://developers.cloudflare.com/workers-ai/platform/pricing/`

Evidence SHA-256:

`ba2d25798a6c594a8ac11e894863345a392b41f8baf98008de0243c3d43e520f`

## Truth boundary

- Gemini remains at its prior verified snapshot value and prior `lastVerified` date because the fresh source fetch did not satisfy the required Free-tier evidence matcher.
- OpenRouter price is carried forward and is not freshly field-verified in the 2026-08-24 snapshot.
- Carried-forward fields do not appear as verified changes.
- The source-intake/promotion run did not mutate runtime data; publication occurs only through the separately reviewed product PR.
