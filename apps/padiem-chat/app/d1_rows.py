"""#5568 follow-on — one normalizer for D1 statement result shapes.

Cloudflare's D1 binding answers `prepare(sql).all()` with a result object whose
rows live under `results`. The 컴2 host (`app.d1_sqlite.SqliteD1`, imported lazily
because it is COM2-only) answers the same call with a bare list of row dicts.
A reader that only recognizes one of the two shapes does not raise: it hands back
zero rows, so a stored list looks empty on the other host.

That is how the PDF → Markdown ledger went invisible on the operating 컴2 host:
jobs and items were written, `first()`/`run()` reads kept working, and every
multi-row read returned nothing.

Every multi-row statement read goes through :func:`rows_from_result` so shape
selection lives in one place instead of per store.
"""
from __future__ import annotations

from typing import Any


def rows_from_result(result: Any) -> list[Any]:
    """Return the row sequence carried by any supported statement shape.

    Accepts `None`, a `{@code {"results": [...]}}` mapping, an object exposing a
    `results` attribute, and a bare list or tuple. An unrecognized shape yields
    an empty list rather than an error, matching a query that returned no rows.
    """
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return list(result)
    rows = getattr(result, "results", None)
    if rows is None and isinstance(result, dict):
        rows = result.get("results")
    if rows is None:
        return []
    if isinstance(rows, (list, tuple)):
        return list(rows)
    try:
        return list(rows)
    except (TypeError, ValueError):
        return []
