"""Shipped worker source for the service-binding contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped worker source, with the sheet path here.
"""
from __future__ import annotations

from pathlib import Path

_WORKER = Path(__file__).resolve().parents[2] / "worker.py"


def worker_source() -> str:
    return _WORKER.read_text(encoding="utf-8")
