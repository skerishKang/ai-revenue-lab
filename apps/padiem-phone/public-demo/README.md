# PADIEM Phone — PUBLIC STATIC DEMO

This directory is a **demonstration only**. It is safe to host as static assets on a Git-connected Cloudflare Pages project.

- Independent, publicly accessible UI demonstrating hypothetical phone-task workflow, templates, simulated IVR/hold/status, task history, phase usage and local TXT result downloads.
- `demo-api.js` implements all mock API methods **in browser memory only**. `app.js` uses `window.publicDemoApi` instead of fetch. No network APIs, servers, cookies, storage, actual customer data, telephony provider, real phone calls or billing.
- User-entered data is never sent to a backend and is cleared when the page reloads. No real customer details should be typed into this public demo.
- CSP `connect-src 'none'`, disabled microphone/camera/geolocation/payment, search indexing off.
- `index.html`, `styles.css`, `app.js`, `demo-api.js`, `assets/padiem-glass-female.jpg`, and `_headers` are the production static package.
- Reuse PADIEM Phone Glass UI and image already present in the repository. This copy is isolated so existing local-only `apps/padiem-phone/server.py` is **never** exposed.
- Cloudflare Pages project must use **GitHub automatic deployments**, root `apps/padiem-phone/public-demo`, production branch `main`, output `.`, and no build command. Do **not** use `wrangler pages deploy` or publish a loopback server.

## Local validation
```powershell
node --check apps/padiem-phone/public-demo/demo-api.js
node --check apps/padiem-phone/public-demo/app.js
python apps/padiem-phone/tests/public_demo_browser_smoke.py
```

Actual website URL is determined only after the Git-connected deployment is verified, not from this README.
