from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
B62_APP = ROOT / "apps" / "padiem-chat" / "app"
B62_PROJECT = ROOT / "apps" / "padiem-chat" / "pyproject.toml"
CORE_PROJECT = ROOT / "packages" / "padiem-ai-core" / "pyproject.toml"
CORE_DOCUMENTS = ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core" / "document_normalization.py"


def test_b62_binary_document_adapter_does_not_own_parser_dependencies() -> None:
    source = (B62_APP / "binary_documents.py").read_text(encoding="utf-8")
    assert "padiem_ai_core.document_normalization" in source
    assert "extract_binary_document" in source
    assert "validate_document_identity" in source
    assert "from pypdf" not in source
    assert "import pypdf" not in source
    assert "from openpyxl" not in source
    assert "import openpyxl" not in source
    assert "ZipFile" not in source
    assert "ElementTree" not in source


def test_b62_ooxml_module_is_only_a_core_compatibility_shim() -> None:
    source = (B62_APP / "ooxml_stdlib.py").read_text(encoding="utf-8")
    assert "padiem_ai_core.document_normalization" in source
    assert "_core_validate_ooxml_archive" in source
    assert "_core_extract_docx_text" in source
    assert "_core_extract_pptx_text" in source
    assert "ZipFile" not in source
    assert "ElementTree" not in source
    assert "PurePosixPath" not in source


def test_b62_text_document_validation_delegates_to_core() -> None:
    source = (B62_APP / "documents.py").read_text(encoding="utf-8")
    assert "padiem_ai_core.document_normalization" in source
    assert "normalize_text_document" in source
    assert "validate_document_identity" in source
    assert "normalize_document_text" in source


def test_document_dependencies_are_owned_by_core_optional_extra() -> None:
    b62_project = B62_PROJECT.read_text(encoding="utf-8")
    core_project = CORE_PROJECT.read_text(encoding="utf-8")
    assert "padiem-ai-core[documents]" in b62_project
    assert '"pypdf' not in b62_project
    assert '"openpyxl' not in b62_project
    assert "documents = [" in core_project
    assert '"pypdf>=6.16.2,<7"' in core_project
    assert '"openpyxl>=3.1,<4"' in core_project


def test_core_document_contract_has_no_path_url_storage_or_provider_authority() -> None:
    source = CORE_DOCUMENTS.read_text(encoding="utf-8")
    assert "def extract_binary_document(*, name: Any, media_type: Any, payload: Any)" in source
    assert "httpx" not in source
    assert "requests" not in source
    assert "Path(" not in source
    assert "open(" not in source
    assert "url" not in source.lower()
    assert "provider" not in source.lower()
