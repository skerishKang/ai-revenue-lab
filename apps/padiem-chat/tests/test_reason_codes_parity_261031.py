"""Parity guard for the duplicated file-lane reason-code catalog (#6338/#6344).

The COM2 file lane refuses a text read with a constant
``DocumentNormalizationError`` code, and Chat maps that code to per-code
guidance. The catalog is duplicated in
``apps/padiem-chat/app/file_lane.py:REASON_CODES`` and
``apps/padiem-file-lane/src/padiem_file_lane/storage.py:PARSER_REASON_CODES``.
A one-sided edit silently sends every refusal back to the generic wording, so
this test imports both lists, requires one identical set, and requires every
code to be one Core's document normalization can actually raise.

Placement: Chat CI installs the Chat app and the shared Core package, so
``app.file_lane`` imports natively. The lane package is pure Python and its
``storage`` module imports only Core and the standard library, so its ``src``
root is added to ``sys.path``. File-lane CI does not install the Chat app, so
it is not the host.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

CHAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CHAT_ROOT.parents[1]
LANE_SRC = CHAT_ROOT.parent / "padiem-file-lane" / "src"
CORE_DIR = REPO_ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core"

if str(LANE_SRC) not in sys.path:
    sys.path.insert(0, str(LANE_SRC))

from app.file_lane import REASON_CODES  # noqa: E402
from padiem_file_lane.storage import PARSER_REASON_CODES  # noqa: E402


def _core_refusal_codes(*paths: Path) -> set[str]:
    """Literal codes Core raises as ``DocumentNormalizationError``.

    The lane parses PDFs through ``padiem_ai_core.pdf_markdown``, which raises
    the same error class, so both modules are part of the catalog the lane draws
    from. A dynamically built code cannot be a constant allowlist entry, so only
    a string-literal first argument counts.
    """

    codes: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            first = node.args[0]
            if (name == "DocumentNormalizationError"
                    and isinstance(first, ast.Constant)
                    and isinstance(first.value, str)):
                codes.add(first.value)
    return codes


def test_chat_and_lane_reason_codes_are_one_catalog() -> None:
    chat = set(REASON_CODES)
    lane = set(PARSER_REASON_CODES)
    assert chat, "Chat REASON_CODES must not be empty"
    assert lane, "lane PARSER_REASON_CODES must not be empty"
    assert chat == lane, (
        "Chat REASON_CODES and file-lane PARSER_REASON_CODES diverged; "
        f"only in Chat: {sorted(chat - lane)}; "
        f"only in the lane: {sorted(lane - chat)}"
    )


def test_every_reason_code_is_a_core_document_refusal() -> None:
    core = _core_refusal_codes(
        CORE_DIR / "document_normalization.py",
        CORE_DIR / "pdf_markdown.py",
    )
    assert core, "Core refusal-code scan found no codes"
    for label, codes in (
        ("Chat REASON_CODES", REASON_CODES),
        ("lane PARSER_REASON_CODES", PARSER_REASON_CODES),
    ):
        unknown = sorted(set(codes) - core)
        assert not unknown, f"{label} contains codes Core cannot raise: {unknown}"
