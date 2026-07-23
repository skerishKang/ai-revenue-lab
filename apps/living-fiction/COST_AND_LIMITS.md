# Cost and Limits — Living Fiction production skeleton

Verified: **2026-07-23** against the official sources listed per section. No
account IDs, hostnames, or secrets appear in this document.

## Stack (all free tiers)

The required production stack is **Modal Starter + Neon Free**. The request
path is `Browser -> Modal FastAPI -> Neon PostgreSQL`; no edge proxy is part
of the required stack (a Cloudflare Worker proxy is an optional future adapter
only — see the note at the end).

| Layer     | Plan                         | Always-on cost | Idle behaviour                     |
| --------- | ---------------------------- | -------------- | ---------------------------------- |
| Compute   | Modal **Starter** ($0/mo)    | $0             | 0 containers when idle             |
| Database  | Neon **Free** ($0/mo)        | $0             | compute suspends after 5 min idle  |

**There is no always-warm resource anywhere in this stack.** Modal is
configured with `min_containers=0` and `buffer_containers=0`; Neon Free
scale-to-zero is mandatory (5-minute idle timeout, cannot be disabled on
Free).

## Quotas and caps as configured

### Modal Starter (verified 2026-07-23 — https://modal.com/pricing)

- $0/month + compute; **$30/month free compute credit** included.
- Plan cap: 100 concurrent containers. This app caps itself far below:
  `max_containers=2`, one concurrent input per container (no
  `@modal.concurrent`), so at most **2 in-flight requests** app-wide.
- Per container: 0.25 vCPU, 512 MB, 60 s scaledown window, 60 s request
  timeout. No GPU, no Volume, no custom domain (Starter has no custom
  domains).
- Billing: per-second — CPU $0.0000131/core/sec (0.125-core minimum), memory
  $0.00000222/GiB/sec. Idle containers bill nothing.
- Runtime DB pool: `psycopg_pool` with `min_size=0`, `max_size=5`,
  `max_idle=60 s`, `max_lifetime=300 s` — an idle container holds **zero**
  PostgreSQL connections, so Neon can scale to zero.

### Neon Free (verified 2026-07-23 — https://neon.com/docs/introduction/plans)

- **100 CU-hours/project/month** (e.g. 0.25 CU × 400 h), autoscaling up to
  2 CU, scale-to-zero after 5 min idle (mandatory on Free).
- 0.5 GB storage/project, 5 GB/month public egress, 10 branches/project.
- Fail-closed on exhaustion: when CU-hours or egress run out, compute is
  **suspended until the next billing period or an explicit upgrade**; when
  storage is full, writes fail. No limit deletes data, and **nothing upgrades
  automatically** — the Free plan has no pay-as-you-go overflow.

## Measuring one reader flow

One reader session (open `/access`, log in with invite, read episode 1,
submit one choice, read the generated branch) produces roughly:

- Modal: ~15–25 requests (HTML + form posts; static-free server-rendered
  pages) across ≤2 containers; a cold start adds one container start
  (~seconds) after idle.
- Neon: a few seconds of compute per burst (connection + queries), then
  scale-to-zero after 5 minutes. Branch generation uses the deterministic
  free MockProvider — **zero AI API cost**.
- Storage growth per flow: a handful of small rows (choice, branch, episode,
  request records) — negligible against 0.5 GB.

At this shape, a single reader flowing through once per day stays inside
every free quota by two orders of magnitude.

## Quota-exhaustion behaviour (fail closed)

- Modal Starter free credit exhausted → deployments stop scheduling until
  credits renew or an operator explicitly upgrades.
- Neon CU-hours/egress exhausted → database compute suspended; the app's
  requests fail with generic 5xx from the pool timeout; no data loss.
- The application itself fails closed on misconfiguration (missing backend
  selection, missing runtime URL, weak/missing secrets, non-current schema)
  at startup rather than serving a degraded surface.

## No automatic paid upgrades

No credit card is required for either of the two free tiers as configured, and
neither of them silently converts to paid usage. Upgrades happen only by an
operator's explicit action.

### Conditions that justify a paid upgrade

1. Need for a custom domain or >2 concurrent containers → Modal Team
   ($250/mo + compute) — evaluate the actual concurrent-reader requirement
   first.
2. Database storage approaching 0.5 GB, or compute need beyond 100
   CU-hours/month → Neon Launch (pay-for-what-you-use, $0.106/CU-hour).
3. A real AI provider replaces the MockProvider → budget per-token provider
   costs separately; this skeleton assumes $0 AI spend.
4. An optional Cloudflare Worker proxy is added in front of Modal (future
   adapter, not required) → Cloudflare Workers Free, then Workers Paid
   ($5/mo) only if its daily quota becomes a constraint.

## Optional future adapter (not required)

A Cloudflare Worker proxy in front of Modal is an optional future adapter only.
It is not part of the required production stack, is not deployed for Issue #77,
and adds no required cost. If one is ever added, it sits between the browser
and Modal; the required stack and its free-tier envelope above are unchanged.

## Sources

- Modal pricing & Starter plan: https://modal.com/pricing (viewed 2026-07-23)
- Neon plans & billing: https://neon.com/docs/introduction/plans (viewed 2026-07-23)
- psycopg pool behaviour: https://www.psycopg.org/psycopg3/docs/api/pool.html
