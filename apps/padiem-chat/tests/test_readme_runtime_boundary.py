from __future__ import annotations

from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
README_PATH = APP_ROOT / "README.md"
B14_CLIENT_PATH = APP_ROOT / "app" / "b14_client.py"


def test_readme_documents_locked_b62_core_b14_boundary():
    readme = README_PATH.read_text(encoding="utf-8")

    assert "Padiem AI Core ExecutionRuntime / StreamingExecutionRuntime" in readme
    assert "B62 converts its product-owned Skill/profile state" in readme
    assert "Business 14 owns provider adapters, provider keys, model catalogs" in readme
    assert "LOW` / `MEDIUM` / `HIGH` product profiles are currently **UNASSIGNED**" in readme
    assert "Provider/model selection remains deferred" in readme

    stale_claims = (
        "Browser → Padiem Chat /api/chat → Business 14 b14/auto → provider/model",
        "B62 calls the fixed Business 14 endpoint using `model=b14/auto`",
    )
    for stale in stale_claims:
        assert stale not in readme


def test_readme_preserves_bounded_multimodal_exception_and_auto_name_truth():
    readme = README_PATH.read_text(encoding="utf-8")
    source = B14_CLIENT_PATH.read_text(encoding="utf-8")

    assert "### Bounded multimodal exception" in readme
    assert "single bounded image" in readme
    assert "does **not** currently use Business 14 `b14/auto` as an active routing decision" in readme
    assert "historical `stream_text_auto` method name is a compatibility entrypoint" in readme

    # Keep the documentation tied to the already-locked #1008/#1009 runtime shape.
    assert "ExecutionRuntime" in source
    assert "StreamingExecutionRuntime" in source
    assert "Despite the historical method name" in source
    assert "does not invoke B14's `b14/auto`" in source
