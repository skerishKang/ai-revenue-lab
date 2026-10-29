# Chat Worker import and local CPU study — draft

This study does not authorize deployment, migration, remote bindings, or external
service contact. Python Worker memory snapshots include top-level imports at
Cloudflare deployment; the local CPython measurement below is not edge CPU.
References: https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/
and https://developers.cloudflare.com/workers/observability/dev-tools/cpu-usage/.
`apps/padiem-chat/wrangler.toml` uses `worker.py`, `python_workers`, compatibility
2026-08-25. Deployment actually using that configuration is not independently proven.
The app itself is created lazily on the first fetch after module import; lazy
imports during or after that initialization can consume request CPU. #6208 must
remain a draft until this is measured against unchanged baseline.

`python -X importtime` on COM2 rehearsal CPython 3.12 (2026-10-29), baseline
source 6f81d32; the relevant files match local e858ce55. One run, wall time
1212.73 ms, installed httpx 0.28.1 and Starlette 1.10.0 differ from the Worker
locked dependency set. CPython stdlib and installed dependencies do not model
Pyodide. Cumulative times overlap; do not sum them. Caller was separately traced,
so an unresolved caller is explicitly unknown. Paths relative to repository unless
marked `venv` or `stdlib`.

| Module | Cumulative ms | First importer |
|---|---:|---|
| httpx | 546.349 | apps/padiem-chat/worker.py:19 |
| httpx._api | 309.845 | venv/httpx/__init__.py:2 |
| httpx._client | 309.670 | venv/httpx/_api.py:6 |
| httpx._auth | 302.474 | venv/httpx/_client.py:13 |
| urllib.request | 285.105 | venv/httpx/_auth.py:9 |
| http.client | 248.069 | stdlib/urllib/request.py:88 |
| httpx._main | 235.987 | UNKNOWN (import-hook limitation) |
| ssl | 234.712 | stdlib/http/client.py:1477 |
| _ssl | 230.584 | stdlib/ssl.py:100 |
| click | 227.521 | venv/httpx/_main.py:8 |
| click.core | 226.202 | venv/click/__init__.py:10 |
| click.types | 220.512 | UNKNOWN (import-hook limitation) |
| click._compat | 206.200 | venv/click/types.py:15 |
| app.main | 166.453 | apps/padiem-chat/worker.py:116 |
| app.app_factory | 152.247 | apps/padiem-chat/app/main.py:22 |
| padiem_ai_core.b14_execution | 148.137 | packages/padiem-ai-core/padiem_ai_core/__init__.py:39 |
| padiem_ai_core | 148.107 | UNKNOWN (import-hook limitation) |
| app.claw_automation_due_workspace_discovery | 79.966 | apps/padiem-chat/worker.py:37 |
| app.claw_automation_scheduled_execution | 52.033 | apps/padiem-chat/worker.py:41 |
| app.claw_automation_background_execution | 51.174 | apps/padiem-chat/app/claw_automation_scheduled_execution.py:17 |

Scheduler modules are used by the separate scheduled lane, not directly by the
four requested HTTP handlers; transitive uses and the full per-request minimal
module sets are unproven. Main/app_factory compose shared routes. Dependencies
loaded does not establish that a particular request needs or executes them.
The login, Google, LoveTree and poll per-route required sets are UNKNOWN pending
actual request instrumentation.

The workflow draft uses a separate minimal local Wrangler config with no live
bindings. It blocks non-loopback IPv4/IPv6 while serving and removes inherited
credentials from the Worker environment. The four deliberately unconfigured
requests are rejection-path experiments, not valid authenticated login/poll or
real OAuth/handoff success flows. Inspector sampling is an estimate, not edge
CPU; status and wall time accompany each sample. No successful execution of the
workflow or parity with deployed snapshots has been demonstrated. Synthetic
local databases, test accounts and signed poll fixtures are still needed.
