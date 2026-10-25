# padiem-document-parser

Private isolated Parser Authority for Padiem Chat (#2824).

Chat cannot run the synchronous `pypdf`/`openpyxl` extraction in its own
Pyodide isolate: a Python Worker has no process isolation and cannot bound or
kill synchronous CPU work. This Worker is that boundary.

```
Chat Worker
  -> DOCUMENT_PARSER_SERVICE (Service Binding, fixed URL /internal/v1/parse)
  -> padiem-document-parser (this Worker)
  -> padiem_ai_core.isolated_parser_service.handle_isolated_parser_request
  -> padiem_ai_core.document_normalization.extract_binary_document (existing parser)
  -> bounded response envelope (document text + page/slide/row provenance)
  -> Chat model context -> B14
```

The wire envelope is owned by `padiem_ai_core.isolated_parser_contract`; this
app adds no parser implementation, no document cap and no caller-selected
parser. Every document-level failure is HTTP 200 with
`{"type": "error", "code": "..."}`; route/method/content-type/size refusals are
non-200 and Chat treats them as an unavailable parser service.

## Exposure

- `workers_dev = false`; no route is configured. The Worker is reachable only
  through the `DOCUMENT_PARSER_SERVICE` Service Binding.
- It holds no D1/R2/KV, no user identity, no model authority and no logging of
  document names or bodies.

## Dependencies and build

`pylock.toml` is the committed lock for
`wasm32-pyodide2025` / CPython 3.13 and contains only pure-Python wheels
(`*-none-any.whl`): `padiem-ai-core[documents]` supplies `pypdf`,
`openpyxl`, `et-xmlfile`, and the same `httpx` runtime the Chat Worker already
vendors. `scripts/build_worker_dependencies.py` enforces that rule, stages the
local path dependency from a copy, installs the lock with
`uv pip install --python-platform wasm32-pyodide2025 --python-version 3.13
--target python_modules --requirements pylock.toml --preview-features pylock
--link-mode copy`, rejects native extensions, and writes a byte-identical
`.worker-src/worker.py` copy.

```bash
cd apps/padiem-document-parser
uv run python scripts/build_worker_dependencies.py
```

The build script prints `status=PASS`, the installed version set and the lock
SHA-256. The same command is the Wrangler `[build]` command.

## Deployment contract (not executed under the CTO freeze)

Merge order:

1. PR #5815 (Core parser + Chat document context) to `main`.
2. This dependent PR (async wire contract, Chat Service Binding injection,
   this Worker) after #5815, because it builds on the same Chat parser files.
3. Deploy `padiem-document-parser` first and verify its version is active.
4. Then deploy Chat. If the binding is present but the parser Worker is not
   deployed, the target does not exist and the Worker fails closed with a
   clear attachment error; it never falls back to in-process parsing.
5. Verify live: `/health` reports `binary_document_attachment_ready: true`
   only after the binding is composed, and one PDF attachment reaches B14.

Rollback order: Chat first (or remove the binding and redeploy Chat), then the
parser Worker. Rolling the parser back while Chat still has the binding fails
closed; it never degrades to the in-process parser.

## Local verification

- `apps/padiem-chat/tests/test_2824_isolated_parser_transport.py`
- `packages/padiem-ai-core/tests/test_isolated_parser_async_contract.py`
- `apps/padiem-document-parser/tests/test_worker_contract.py`

These use an in-memory Service Binding fake over the real parser handler and
real synthetic PDF/DOCX/PPTX/XLSX bytes; they do not replace production Worker
verification.
