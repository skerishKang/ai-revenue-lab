# Cloudflare Workers proxy (Phase B — operator run)

A thin, stateless proxy on the **Workers Free** plan that fronts the Modal app
with a stable public hostname. The worker holds no secrets and no state; the
upstream origin comes from the `UPSTREAM_ORIGIN` environment variable.

## What the worker does

- Forwards method, body, query string, and headers to the fixed upstream
  (never an open proxy — the destination is configuration-only).
- Sets `Host` to the upstream host; adds `X-Forwarded-Host` /
  `X-Forwarded-Proto` with the original values.
- Passes the browser `Origin` through unchanged so the app verifies it against
  `LF_ALLOWED_ORIGINS` (which must be this worker's public hostname).
- Answers CORS preflight only for same-host origins; never allows arbitrary
  cross-origin access.
- Passes `Set-Cookie` through untouched (cookies scope to the worker
  hostname).
- Rewrites redirect `Location` headers that carry the upstream host back to
  the user-facing hostname.
- Forces `Cache-Control: no-store` on every response; nothing is cached.
- Bounded 30 s upstream timeout → generic `504`; upstream failure → generic
  `502`; misconfiguration → generic `500`. No error body reveals the upstream
  URL.
- Does not block any path, so the reader `/access` flow is untouched.

## Deploy

1. Install wrangler and log in:

   ```bash
   npm install -g wrangler
   wrangler login
   ```

2. Create the config from the example and fill in the upstream from the
   `modal deploy` output:

   ```bash
   cd apps/living-fiction/deploy/cloudflare
   cp wrangler.toml.example wrangler.toml
   # edit wrangler.toml: UPSTREAM_ORIGIN = "https://ai-revenue-living-fiction--<your-team>.modal.run"
   ```

3. Deploy:

   ```bash
   wrangler deploy
   ```

4. Point the app's allowlist at the new hostname: update the Modal secret
   (`LF_ALLOWED_ORIGINS=https://living-fiction-proxy.<your-subdomain>.workers.dev`)
   and redeploy the Modal app.

5. Verify:

   ```bash
   curl https://living-fiction-proxy.<your-subdomain>.workers.dev/health
   ```

## Protecting `/admin/*` with Cloudflare Access

The worker itself does not gate paths. Put the admin surface behind Cloudflare
Access (Zero Trust, free for up to 50 users):

1. Cloudflare dashboard → **Zero Trust** → **Access** → **Applications** →
   **Add an application** (Self-hosted).
2. Application domain: the worker hostname.
3. Add a policy covering path prefix `/admin/*` only, with an **Email OTP**
   (one-time-pin) rule for your operator address.
4. Do **not** add a policy for `/access` or any other reader path — reader
   login uses the application's own invite-code flow.

## Free-plan limits that matter

- 100,000 requests/day, then Error 1027 (set the route to **fail closed**).
- 10 ms CPU time per request (this proxy does no compute-heavy work; waiting
  on the upstream does not count).
- 50 subrequests per request (this proxy makes exactly one).

See `../../COST_AND_LIMITS.md` for the full quota and upgrade policy.
