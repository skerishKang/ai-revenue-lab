# B66 generic analyzer / compiler

Generic, template-agnostic source-to-certified-template pipeline for B66
quotation reproduction. Introduced by #3628 under #3595.

**Document role:** this is a **development-tool implementation README**, not
the product's upload/registration allowlist, deployment authority, customer
acceptance, or a Production runtime activation statement. The product lifecycle
and execution eligibility belong to the
[B66 canonical README](../../docs/products/b66/README.md) and the
[source reproduction/certification contract](../../docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md).
The generic second-template proof is a **source/benchmark certification**, not
proof of a current deployed customer account journey.

```text
SOURCE (xlsx) + REFERENCE (pdf)
  -> analyze.py            raw observations only (no semantics)
  -> compile_generic.py    label-anchored semantic slots + geometric structure
  -> render.py             deterministic renderer (baseline byte-copy / isolated overlay)
  -> certify.py            separately-measured critical fidelity gates
  -> validate_mutations.py bounded mutation robustness (outside-allowed pixels = 0)
  -> literal_scan.py       proves the generic modules carry no document fact
```

## Generality contract

`compile_generic.py` must contain **no** document-specific cell reference, no
document-specific coordinate constant and no customer literal. Slot roles are
inferred from the source's own field labels (`견적번호`, `작성일자`, `제출처`,
`건명`, …), the item table from its column-name tokens, and the totals block
from the totals vocabulary. The only literals permitted are that generic Korean
quotation vocabulary and generic formatting rules.

This replaces the CGI-specific compiler, which hardcoded `K4/K5/K7/K9`, `B13`,
`E/F/G 14..16`, `G22:G24`, `C23`, `A11` and `CAMERA_Y_MAX=275`.

## Evidence

### Recorded independent, real-document certification (not rerun by public tests)

`evidence/second_template_certification_summary.json` records the historical
certification of a **materially different second quotation** (private real
quotation; source and customer facts are not committed, only hashes and gate
results). The figures below are the **recorded evidence artifact**, not fresh
measurements from the public-safe synthetic fixture:

```text
page orientation      portrait -> landscape
header field block    right-aligned -> left-aligned
item table columns    contiguous -> gapped (A,B,D,E,F,G,I,L)
totals wording        소계/부가세/합계 -> [소계]/[V.A.T]/[총계]
camera object         present -> absent
source sheet merges   23 -> 80
```

```text
BASELINE_BYTE_IDENTICAL=YES
CRITICAL_GATES=14/14 PASS
RASTER_SIMILARITY=0/0/0 (72/150/300 dpi)
MUTATION_CASES=14  PASS=11  REJECTED=3  FAIL=0
MAX_OUTSIDE_ALLOWED_CHANGED_PIXELS=0
GENERIC_LITERAL_IN_GENERIC_MODULES=0
```

The recorded critical gates, DPI raster results and mutation case counts must
not be presented as the outcome of rerunning the unrelated public fixture.
The real customer source files are not required for the public regression
suite and are not included in the repository.

### What each gate measures now (#3595 follow-up)

The recorded `14/14` above is the historical artifact of the run that produced
it. Two of those names were second names for one comparison, so the current
`certify.py` reports **13** critical gates and each one comes from its own
observation:

```text
BASELINE_BYTE_IDENTICAL  whole-file sha256
PAGE_GEOMETRY            page rectangle
TEXT_POSITION            per-span origin (x, y)
FONT_FAMILY / FONT_SIZE  the font-name and font-size sets
TEXT_SPACING_BASELINE    per-span advance extents + font/size/colour (no origin)
WRAP_SHRINK              line-break structure (lines, spans and characters per
                         line, reading order — no coordinates)
LAYOUT_GEOMETRY          every drawing: rect, kind, fill and stroke colour
TABLE_LINES_BORDERS      stroke-only drawings incl. stroke width and dashes
IMAGE_PLACEMENT          sorted image rectangles
STAMP_ALPHA              how many images carry a soft mask
ASSET_LAYERING           image paint order as a permutation of the placement
REFERENCE_VALUE_PARITY   compiled values exist as source cell values
RASTER_SIMILARITY        whole-page pixels at 72/150/300 dpi (also required = 0)
```

Honest limits, kept visible instead of hidden behind extra names:

- **Logo and stamp are not separate gates.** The compiled template carries no
  semantic asset roles, so image gates treat every image the same way. The old
  `LOGO_GEOMETRY` / `STAMP_GEOMETRY` pair measured one comparison under two
  names and was removed rather than kept as an alias.
- **`ASSET_LAYERING` is image-against-image order only.** MuPDF does not expose
  how images interleave with vector paint, so this gate does not claim
  image-versus-vector layering.

`tests/test_b66_generic_gate_independence.py` pins those distinctions: a rule
width change must move only `TABLE_LINES_BORDERS`, a fill colour change only
`LAYOUT_GEOMETRY`, a moved image only `IMAGE_PLACEMENT`, a soft-mask change only
`STAMP_ALPHA`, and a z-order swap only `ASSET_LAYERING`.

### Benchmark renderer versus customer-PDF security boundary

`render.py` is a **deterministic certification benchmark**: unchanged values
return a byte-identical base PDF, while mutated values are drawn in isolated
overlays without rewriting the original content streams. This proves
the **declared benchmark geometry and permitted-area mutation gates**.

It does **not** by itself prove that superseded customer text in a changed
PDF slot is removed from copy/search extraction. The separately reviewed
**product integration** clears stale text inside changed compiled-slot covers
before rendering replacement content, then independently checks stale-text,
font-resource and outside-region invariants. These are distinct certification
scopes; refer to the
[B66 fidelity contract](../../docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md).
Do not interpret a benchmark pass or byte-identical no-op result as blanket
Production/customer-readiness approval.

## Tests

`tests/test_b66_generic_compile.py` runs the whole pipeline on the public-safe
synthetic fixture (`tests/fixtures/`, generated by
`make_synthetic_fixture.py`) and asserts baseline byte-identity, all critical
gates, mutation isolation and zero generic-module literals.

This suite runs in CI: the B66 workflow job
`b66-generic-pipeline-certification` installs the hash-pinned PDF engine
(`requirements-certification.txt`), installs `fonts-nanum` (the metrics the
isolation gates measure; a host without a font makes `render.py` refuse with
`REJECT_NO_FONT` instead of substituting a wider one) and fails the lane if any
collected case is skipped.

### Public-safe synthetic-fixture regression (separate from recorded evidence)

From the repository root:

**Linux / macOS (bash):**

```bash
PYTHONUTF8=1 python -m pytest -q tools/b66_generic/tests/test_b66_generic_compile.py
```

**Windows PowerShell:**

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
python -m pytest -q tools/b66_generic/tests/test_b66_generic_compile.py
```

The commands exercise **three** synthetic-fixture tests: baseline reproduction
and separately measured certification, bounded mutation isolation, and generic
literal scanning. On the reviewed Windows checkout (2026-10-08), the suite
reported **3 passed**; that is *not* a rerun of the historical private second
quotation or any Production end-to-end workflow.

PyMuPDF (`fitz`) and `pytest` are needed. The test module uses
`pytest.importorskip("fitz")`: when PyMuPDF is absent it may **skip** rather
than fail. Confirm the resulting pass/skip counts; an all-skipped run does
**not** establish a tested result.
