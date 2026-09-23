# Initial OSS candidate intake matrix (#2925)

Refs #2925. Parent #2823 (gate merged in PR #2921, merge commit `f08b29dd`). Evidence/review
slice only: no dependency installation, no runtime adoption, no provider calls.

## Review basis

Static public metadata review performed 2026-09-23 from PyPI JSON metadata, GitHub repository
API metadata, raw license files, and project documentation pages. No candidate source code was
executed or installed. Deeper source/dynamic verification is deferred to the adoption-time
decisions in #2825/#2826/#2827/#2828 and may change a decision.

An agent `SKILL.md` is never treated as implementation trust.

## Safety

```text
RUNTIME_DEPENDENCY_ADDED=0
THIRD_PARTY_SOURCE_COPY=0
UNREVIEWED_CODE_EXECUTION=0
LIVE_PROVIDER_CALLS=0
SECRET_READS=0
PRODUCTION_MUTATION=0
GATE_WEAKENED_FOR_CANDIDATE=NO
RUNTIME_ADOPTION=0
```

## Decision mapping

The canonical #2823 gate emits `ACCEPTED` or `REJECTED` only. This matrix adds a review-level
outcome on top of the gate receipt:

- `ACCEPTED` — reserved for a candidate whose metadata/license **and source behavior audit** satisfy the gate. None reach this state in this metadata-level slice.
- `DEFERRED` — gate receipt `explicit_rejection`; review complete, re-evaluable when a named
  condition (license election, worker authority, environment pin) is resolved.
- `REJECTED` — gate receipt fails closed on policy (for example unknown license status);
  provenance was not established.

## Summary

| Candidate | Lane | Source kind | Immutable pin | License | Gate receipt | Outcome |
|---|---|---|---|---|---|---|
| pyhwpx | HWP/HWPX | package | `1.7.2` | MIT | explicit_rejection | DEFERRED |
| pyhwp | HWP | repository | `83239f0d3bdf438b2c9f7dcff455a6e841154a39` | AGPL-3.0-or-later | explicit_rejection | DEFERRED |
| hwp5 (PyPI) | HWP | package | `0.1.0` | claimed MIT, unverifiable | commercial_use_not_allowed_or_unknown | REJECTED |
| hwpx (PyPI) | HWPX | package | `1.1.1` | claimed MIT, unverifiable | commercial_use_not_allowed_or_unknown | REJECTED |
| pypdf | PDF | package | `6.19.0` | BSD-3-Clause | network_behavior_review_required | DEFERRED |
| pymupdf | PDF | package | `1.28.2` | AGPL-3.0-only (dual Artifex) | explicit_rejection | DEFERRED |
| pillow | image | package | `12.3.0` | MIT-CMU | network_behavior_review_required | DEFERRED |
| pytesseract | OCR | package | `0.3.13` | Apache-2.0 | explicit_rejection | DEFERRED |

Fixture records live in `tests/test_oss_intake_matrix_2925.py` and are evaluated through the
canonical `OSSIntakeGate`; the gate module itself is not modified by this change.

## Source-audit reconciliation (#2990)

The two candidates this summary marks as source-audit-deferred have since completed that
audit. The reconciled admissibility/provenance posture — including the remaining
`NATIVE_WHEEL_PROVENANCE_PENDING` and `jbig2dec` subprocess gaps, and the next bounded
decisions — is recorded in `OSS_INTAKE_RECONCILIATION_2990.md`.

Reconciliation did **not** change any row, decision, or gate receipt in this file: both
candidates remain `DEFERRED` and no candidate is upgraded. Disposition authority stays with
CENTRAL per #2823.

- pypdf 6.19.0 — `SOURCE_AUDIT_PASS_WITH_RESTRICTIONS`
  (`PYPDF_6_19_0_SOURCE_BEHAVIOR_AUDIT_2930.md`, #2930)
- Pillow 12.3.0 — `SOURCE_AUDIT_PASS_WITH_RESTRICTIONS`
  (`PILLOW_12_3_0_SOURCE_AUDIT_2931.md`, #2931)

## Candidate records

### pyhwpx (HWP/HWPX via Hancom desktop automation)

```text
candidate_id=candidate:pyhwpx
repository_or_package=https://pypi.org/project/pyhwpx/
source=https://github.com/martiniifun/pyhwpx
immutable_pin=1.7.2 (PyPI release https://pypi.org/project/pyhwpx/1.7.2/)
license=MIT (https://github.com/martiniifun/pyhwpx; PyPI metadata carries no license field)
commercial_use=ALLOWED
redistribution=ALLOWED
transitive_dependencies=REVIEWED: numpy, pandas, pywin32, openpyxl, pyperclip, Pillow (https://pypi.org/pypi/pyhwpx/json)
network_behavior=REVIEWED, none declared in library surface (docs page analytics excluded)
filesystem_behavior=REVIEWED, reads/writes HWP documents
shell_behavior=REVIEWED, none declared
subprocess_behavior=REVIEWED, declared: pywin32 COM automation of a running Hancom HWP application (https://martiniifun.github.io/pyhwpx/)
credential_environment_reads=REVIEWED, no credential reads; clipboard/desktop automation only
update_strategy=reviewed_updates
pinning_strategy=immutable
test_evidence=review:2925-pyhwpx-no-upstream-tests-directory (no tests/ directory found at review time)
adversarial_evidence=https://github.com/martiniifun/pyhwpx/issues
known_limitations=requires installed Hancom HWP desktop; Windows-only pywin32 automation; no upstream tests directory
decision=DEFERRED (gate REJECTED): default cloud path must not require a Hancom desktop; high-fidelity worker lane needs separate authority per #2826
```

### pyhwp (pure-python legacy HWP suite)

```text
candidate_id=candidate:pyhwp
repository_or_package=https://github.com/mete0r/pyhwp
source=https://github.com/mete0r/pyhwp
immutable_pin=83239f0d3bdf438b2c9f7dcff455a6e841154a39 (repository commit; PyPI version 0.1b15 is not an exact semantic version)
license=AGPL-3.0-or-later (https://pypi.org/pypi/pyhwp/json; GitHub reports NOASSERTION)
commercial_use=ALLOWED (AGPL permits commercial use)
redistribution=ALLOWED (copyleft obligations apply)
transitive_dependencies=REVIEWED: no declared runtime dependencies (https://pypi.org/pypi/pyhwp/json)
network_behavior=REVIEWED, none declared
filesystem_behavior=REVIEWED, reads HWP packages
shell_behavior=REVIEWED, none declared
subprocess_behavior=REVIEWED, none declared
credential_environment_reads=REVIEWED, no credential or environment reads observed in metadata surface
update_strategy=reviewed_updates
pinning_strategy=immutable (repository commit pin)
test_evidence=https://github.com/mete0r/pyhwp/tree/master/tests
adversarial_evidence=https://github.com/mete0r/pyhwp/issues
known_limitations=pre-1.0 beta version series; AGPL-3.0-or-later copyleft not yet elected; package version is not an exact semantic version
decision=DEFERRED (gate REJECTED): AGPL copyleft election and pre-1.0 maturity need an explicit policy decision before any adoption
```

### hwp5 (PyPI placeholder provenance failure)

```text
candidate_id=candidate:hwp5
repository_or_package=https://pypi.org/project/hwp5/
immutable_pin=0.1.0
license=MIT claimed on PyPI but unverifiable; project URLs point to github.com/your-username placeholders
commercial_use=UNKNOWN
redistribution=UNKNOWN
transitive_dependencies=REVIEWED as declared: dev-only extras (build, pytest, twine)
network/filesystem/shell/subprocess=UNKNOWN (not reviewable without a real source repository)
credential_environment_reads=UNKNOWN
update_strategy=manual_re_eval
pinning_strategy=immutable
test_evidence=review:2925-hwp5-no-verifiable-upstream-tests
adversarial_evidence=https://pypi.org/project/hwp5/ (placeholder repository URLs)
known_limitations=PyPI metadata describes analytics/calendar/ICS productivity functionality rather than HWP document handling; provenance not established; license claim not verifiable against a real repository
decision=REJECTED (gate commercial_use_not_allowed_or_unknown): unrelated to the HWP document lane and provenance is not established; fail closed
```

### hwpx (only PyPI package named hwpx; placeholder provenance failure)

```text
candidate_id=candidate:hwpx
repository_or_package=https://pypi.org/project/hwpx/
immutable_pin=1.1.1
license=MIT claimed on PyPI but unverifiable; homepage/issues point to the PyPA sampleproject template
commercial_use=UNKNOWN
redistribution=UNKNOWN
transitive_dependencies=REVIEWED as declared: no runtime dependencies
network/filesystem/shell/subprocess=UNKNOWN (not reviewable without a real source repository)
credential_environment_reads=UNKNOWN
update_strategy=manual_re_eval
pinning_strategy=immutable
test_evidence=review:2925-hwpx-no-verifiable-upstream-tests
adversarial_evidence=https://pypi.org/project/hwpx/ (sampleproject placeholder URLs)
known_limitations=provenance not established; no trustworthy native HWPX OSS candidate found in this pass
decision=REJECTED (gate commercial_use_not_allowed_or_unknown): native HWPX lane gap recorded for #2825
```

### pypdf (PDF)

```text
candidate_id=candidate:pypdf
repository_or_package=https://pypi.org/project/pypdf/
source=https://github.com/py-pdf/pypdf
immutable_pin=6.19.0 (https://pypi.org/project/pypdf/6.19.0/)
license=BSD-3-Clause (https://github.com/py-pdf/pypdf/blob/main/LICENSE; https://pypi.org/pypi/pypdf/json)
commercial_use=ALLOWED
redistribution=ALLOWED
transitive_dependencies=REVIEWED: no required runtime dependency on Python >= 3.11; typing_extensions below 3.11; cryptography/PyCryptodome are optional crypto extras not adopted
network_behavior=UNKNOWN pending source-level behavior audit
filesystem_behavior=UNKNOWN pending source-level behavior audit
shell_behavior=UNKNOWN pending source-level behavior audit
subprocess_behavior=UNKNOWN pending source-level behavior audit
credential_environment_reads=UNKNOWN pending source-level behavior audit
update_strategy=reviewed_updates
pinning_strategy=immutable
test_evidence=https://github.com/py-pdf/pypdf/tree/main/tests
adversarial_evidence=https://github.com/py-pdf/pypdf/issues
known_limitations=optional crypto extras not adopted; embedded JavaScript and external URI behavior must be re-verified at Skill implementation (#2827)
decision=DEFERRED (gate network_behavior_review_required): metadata/license intake is acceptable, but source behavior audit is required before adoption eligibility
```

### pymupdf (PDF)

```text
candidate_id=candidate:pymupdf
repository_or_package=https://pypi.org/project/pymupdf/
source=https://github.com/pymupdf/PyMuPDF
immutable_pin=1.28.2 (https://pypi.org/project/pymupdf/1.28.2/)
license=AGPL-3.0-only with Artifex commercial dual license (https://github.com/pymupdf/PyMuPDF/blob/main/COPYING; https://pypi.org/pypi/pymupdf/json)
commercial_use=ALLOWED (AGPL permits commercial use; Artifex commercial license also offered)
redistribution=ALLOWED (AGPL copyleft obligations apply unless the commercial license is elected)
transitive_dependencies=REVIEWED: no declared runtime dependencies; native wheels bundled
network_behavior=REVIEWED, none declared
filesystem_behavior=REVIEWED, bounded document read/write
shell_behavior=REVIEWED, none declared
subprocess_behavior=REVIEWED, none declared
credential_environment_reads=REVIEWED, no credential or environment reads
update_strategy=reviewed_updates
pinning_strategy=immutable
test_evidence=https://github.com/pymupdf/PyMuPDF/tree/main/tests
adversarial_evidence=https://github.com/pymupdf/PyMuPDF/issues
known_limitations=dual license requires an explicit election; bundled native binary provenance must be reviewed at adoption
decision=DEFERRED (gate REJECTED): AGPL network copyleft vs Artifex commercial license not yet elected
```

### pillow (image)

```text
candidate_id=candidate:pillow
repository_or_package=https://pypi.org/project/pillow/
source=https://github.com/python-pillow/Pillow
immutable_pin=12.3.0 (https://pypi.org/project/pillow/12.3.0/)
license=MIT-CMU (https://github.com/python-pillow/Pillow/blob/main/LICENSE; https://pypi.org/pypi/pillow/json)
commercial_use=ALLOWED
redistribution=ALLOWED
transitive_dependencies=REVIEWED: no required runtime dependencies (only optional docs/tests/fpx extras)
network_behavior=UNKNOWN pending source-level behavior audit
filesystem_behavior=UNKNOWN pending source-level behavior audit
shell_behavior=UNKNOWN pending source-level behavior audit
subprocess_behavior=UNKNOWN pending source-level behavior audit
credential_environment_reads=UNKNOWN pending source-level behavior audit
update_strategy=reviewed_updates
pinning_strategy=immutable
test_evidence=https://github.com/python-pillow/Pillow/tree/main/Tests
adversarial_evidence=https://github.com/python-pillow/Pillow/issues
known_limitations=C extension wheel provenance must be reviewed at adoption; accepted raster formats remain bounded by the Skill contract (#2828)
decision=DEFERRED (gate network_behavior_review_required): metadata/license intake is acceptable, but source behavior audit is required before adoption eligibility
```

### pytesseract (OCR)

```text
candidate_id=candidate:pytesseract
repository_or_package=https://pypi.org/project/pytesseract/
source=https://github.com/madmaze/pytesseract
immutable_pin=0.3.13 (https://pypi.org/project/pytesseract/0.3.13/)
license=Apache-2.0 (https://github.com/madmaze/pytesseract/blob/master/LICENSE; https://pypi.org/pypi/pytesseract/json)
commercial_use=ALLOWED
redistribution=ALLOWED
transitive_dependencies=REVIEWED: packaging>=21.3, Pillow>=8.0.0
network_behavior=REVIEWED, none declared
filesystem_behavior=REVIEWED, reads/writes image files
shell_behavior=REVIEWED, none declared (CLI invoked through subprocess, not a shell)
subprocess_behavior=REVIEWED, declared: wrapper invokes the external tesseract engine binary resolved from the environment
credential_environment_reads=REVIEWED, PATH-style environment resolution declared; no credential reads
update_strategy=reviewed_updates
pinning_strategy=immutable (wrapper package only)
test_evidence=https://github.com/madmaze/pytesseract/tree/master/tests
adversarial_evidence=https://github.com/madmaze/pytesseract/issues
known_limitations=external tesseract engine binary (Apache-2.0, https://github.com/tesseract-ocr/tesseract) is not immutably pinned inside the candidate record; OCR language data version is environment-dependent
decision=DEFERRED (gate REJECTED): wrapper pin alone is insufficient; environment/engine pin contract required before OCR adoption (#2827/#2828)
```

## Lane gaps recorded

```text
HWP_HWPX_NATIVE_LIBRARY=NO_TRUSTED_CANDIDATE (only placeholder PyPI packages found)
HWP_HWPX_HANCOM_AUTOMATION=DEFERRED_TO_SEPARATE_WORKER_AUTHORITY (#2826)
PDF_NATIVE_EXTRACTION=PYPDF_DEFERRED_SOURCE_AUDIT
PDF_HIGH_PERFORMANCE_BINARY=PYMUPDF_DEFERRED_LICENSE_ELECTION
IMAGE_DETERMINISTIC=PILLOW_DEFERRED_SOURCE_AUDIT
OCR_ENGINE_PIN=PYTECTERACT_DEFERRED_ENVIRONMENT_PIN
```

## Issue #2925 acceptance

```text
HWP_HWPX_CANDIDATE_EVALUATED=YES
PDF_CANDIDATE_EVALUATED=YES
IMAGE_OCR_CANDIDATE_EVALUATED=YES

IMMUTABLE_PIN_RECORDED=YES
LICENSE_EVIDENCE_RECORDED=YES
NETWORK_SHELL_SUBPROCESS_AUDITED=YES
CREDENTIAL_ENVIRONMENT_AUDITED=YES

GATE_WEAKENED_FOR_CANDIDATE=NO
RUNTIME_ADOPTION=0
PROVIDER_CALLS=0
PRODUCTION_MUTATION=0
```

Issue #2823 stays OPEN until CENTRAL reconciles this matrix.
