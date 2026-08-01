"""FastAPI application entrypoint.

SYNTHETIC DEVELOPMENT AUTHORITY ONLY
NOT AUTHENTICATION
MUST NOT BE ENABLED IN PRODUCTION

Run locally:  uvicorn app.main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router
from .domain import DomainError

DESCRIPTION = """
# Business 29 — minimal governance ledger backend (Phase 3A)

## SYNTHETIC DEVELOPMENT AUTHORITY ONLY
## NOT AUTHENTICATION
## MUST NOT BE ENABLED IN PRODUCTION

Local-only backend for the meeting-to-public-notice governance ledger.

- synthetic fixture data only (솔빛마루 2단지 / Solbit Maru 2, 420 households)
- local SQLite test database; PostgreSQL-compatible design target
- no real authentication (synthetic actor headers `X-Synthetic-Actor`, `X-Synthetic-Role`)
- no personal data · no production deployment · no legal judgement
- no real electronic voting · no K-apt write integration
- no binary upload (document metadata only)

Idempotent mutation endpoints require `idempotencyKey`.
"""

app = FastAPI(
    title="Business 29 Governance Ledger Backend",
    version="0.1.0",
    description=DESCRIPTION,
    openapi_tags=[{"name": "api", "description": "Governance ledger endpoints"}],
)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.http_status, content=exc.to_body())


@app.get("/health")
def health():
    return {"status": "ok", "synthetic": True, "auth": "NOT_AUTHENTICATION"}


app.include_router(router)
