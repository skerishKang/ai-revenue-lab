# B54 Claw Document Export Architecture & Format Decisions (#2016)

- Status: REVIEWED / MVP
- Issue: #2016 — [B54][Claw MVP] Document export — 견적서/발주서 초안을 DOCX/HWPX 파일로 생성
- Scope: Document export module for Korean business quote and order drafts

---

## 1. Executive Summary

Claw MVP produces structured draft business documents (견적서, 발주서/판매오더). While markdown (.md) is the native internal representation, Korean business practice requires distributable office formats:
1. **DOCX** (Office Open XML): Fully implemented using Python standard library (zipfile, XML serialization). Produces standard-conforming OOXML documents without heavy external dependencies.
2. **HWPX** (Hangul Word Processor XML format): Documented decision. Not implemented in this slice to prevent untested XML schemas or incomplete packaging. Fails closed with an explicit descriptive error.
3. **Legacy HWP** (Binary compound file format): Explicit non-goal. Proprietary binary specification is unsupported.

### Format Decision Record
```text
DOCX_EXPORT = FULLY_IMPLEMENTED_STANDARD_OOXML
HWPX_EXPORT = DOCUMENTED_DECISION
LEGACY_HWP_EXPORT = UNSUPPORTED_BINARY_HWP_NON_GOAL
MD_EXPORT_DEFAULT = PRESERVED_BYTE_IDENTICAL
REAL_PROVIDER_CALLS = 0
CREDENTIAL_WORK = 0
PRODUCTION_MUTATION = 0
```

---

## 2. DOCX Implementation Architecture

The DOCX exporter builds a minimal, standard-conforming ECMA-376 / ISO/IEC 29500 WordprocessingML container without third-party dependencies:
- **Zip Package Structure**:
  - `[Content_Types].xml`: Declares default content types (application/xml, relationships) and word document override.
  - `_rels/.rels`: Package relationship pointing to word/document.xml.
  - `word/document.xml`: WordprocessingML body containing:
    - Document header / title.
    - Metadata summary (저장소, 문서 유형, 입력 파일, 승인 근거, P01 실행 상태).
    - Document body text (anti-hallucination draft answer).
    - Item table (품명, 수량, 단가, 금액, 합계).
    - Flow calculation validation footer.
- **Safety & Robustness**:
  - All textual content is XML-escaped (&, <, >, ", ').
  - Unicode characters (including Korean hangul syllables and symbols) are preserved in UTF-8.
  - Fail-closed path validation and atomic writing.

---

## 3. HWPX Documented Decision

- **Decision**: `HWPX_EXPORT = DOCUMENTED_DECISION`
- **Rationale**: HWPX is an OWPML zip package requiring multiple sub-components (Contents/section0.xml, Contents/header.xml, FileHeader/version.xml, etc.) with strict Hancom-specific XML namespaces. To avoid generating non-conforming or corrupted HWPX files without a dedicated validator in CI, HWPX is deferred to a dedicated follow-up issue.
- **Behavior**: When requested with `--format hwpx`, the flow fails closed with `document_format_unsupported` explaining the documented decision and directing users to `--format docx` or `--format md`.

---

## 4. Legacy HWP Non-Goal

- **Decision**: `LEGACY_HWP_EXPORT = UNSUPPORTED_BINARY_HWP_NON_GOAL`
- **Rationale**: Legacy HWP is a proprietary binary format prone to security issues and unsupported without heavy native tools.
- **Behavior**: Requests for .hwp fail closed immediately.

---

## 5. CLI & Flow Integration

- Added `--format docx|hwpx|md` (default: md) to `kagent draft` and `kagent order`.
- When `--format md` is selected, output remains completely unchanged and byte-identical.
- When `--format docx` is selected, out_path is written as a valid DOCX OOXML zip package.
