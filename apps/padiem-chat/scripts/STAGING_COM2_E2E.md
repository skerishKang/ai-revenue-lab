# COM2 staging Chat e2e checks

Runs eight contract checks against an isolated CPython Chat: health, guest and
signed-in auth status, first mock chat turn and conversation creation,
conversation list, owner project-file list, attachment capabilities and PC
device-card status.

The suite performs a write: each run creates a conversation. Use an isolated
staging database and a disposable staging account. It accepts only an HTTP
loopback origin, disables proxies and redirects, and requires health runtime
`mock` before writing. Configure the staging app's local-dev public origin to
match the supplied URL, enable mock runtime, and prepare an authenticated staging
session with history enabled. It does not create credentials or log in.

Set `STAGING_CHAT_COOKIE` privately to the complete session Cookie header
(e.g. `padiem_session=<value>`) in the process environment, never in a
command line, source file, log, or shared shell history. Without the variable
the suite runs the two guest checks only and reports the six login-dependent
checks as `SKIP` (no requests, no writes). Run on the machine hosting staging:

```sh
python apps/padiem-chat/scripts/staging_com2_e2e.py http://127.0.0.1:8801
```

Use another loopback port if needed. Exit 0 means every check that could run
passed (`PASS 8 checks` signed in, `PASS 2 checks` + `SKIP 6 checks` guest
only); exit 1 means a check or request failed. Output contains check names and
exception class only. Remove the environment variable after use using your
shell's normal mechanism. This verifies response contracts, not data parity or
real model behavior. The disposable conversation remains in staging.

Project files: the auth status `project_files_ready` field determines whether
the suite expects a 200 list or 503 `project_files_unavailable`. PC status:
`available` selects the device-list or unavailable contract. Attachment
capabilities similarly report ready or unavailable. An unavailable dependency
does not establish that the dependency itself works.

Local regression (from apps/padiem-chat, with existing project dependencies):
```sh
python -m pytest tests/test_staging_com2_e2e_suite.py -q --tb=no
```
The test starts the existing Chat app over loopback with mock model and in-memory
fixtures, exercises both file and PC readiness states, and checks address
rejection. Do not point it at production.
