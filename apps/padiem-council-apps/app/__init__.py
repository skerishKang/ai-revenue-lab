"""PADIEM council apps (의원3종) — independent entry app.

Three standalone product modules (speech / SNS / meeting) served from their
own static entry point. The app owns no AI engine, router, auth system or
store: the browser modules call the existing PADIEM contracts directly
(``POST /api/chat`` B14 lane, ``/api/projects`` file store, session cookie
auth via ``GET /api/auth/status``). See README.md for the reuse and
not-yet-connected boundaries.
"""
