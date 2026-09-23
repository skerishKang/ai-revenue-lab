# OSS intake reconciliation — pypdf 6.19.0 and Pillow 12.3.0 (#2990)

Refs #2990. Parent #2823. Program parent #2821.
Predecessors #2925 (intake matrix, PR #2928), #2930 (pypdf audit, PR #2932),
#2931 (Pillow audit, PR #2934).

This artifact **does not** change any candidate disposition. It reconciles the
two completed source-behavior audits into one admissibility/provenance posture
and names the remaining provenance children. The canonical #2925 matrix
(`OSS_CANDIDATE_INTAKE_MATRIX_2925.md`) is edited by this change only to point
at this reconciliation; every candidate row and decision there is preserved
byte-for-byte.

## Non-equivalence (binding)

```text
METADATA_LICENSE_REVIEW != SOURCE_BEHAVIOR_AUDIT != RUNTIME_ADOPTION
SOURCE_AUDIT_PASS_WITH_RESTRICTIONS != ADOPTION_ELIGIBLE
NATIVE_BINARY_PROVENANCE_PENDING != NATIVE_BINARY_PROVENANCE_ACCEPTED
PILLOW_OR_PYPDF_INTERNAL_GUARDS != PADIEM_FILE_INTAKE_AUTHORITY
UNKNOWN_REMAINS_UNKNOWN
```

## Safety counters

```text
RUNTIME_DEPENDENCY_ADDED=0
PACKAGE_INSTALL=0
CANDIDATE_EXECUTION=0
THIRD_PARTY_SOURCE_COPY=0
UNREVIEWED_CODE_EXECUTION=0
RUNTIME_REGISTRATION=0
SKILL_REGISTRATION=0
LIVE_PROVIDER_CALLS=0
SECRET_READS=0
GATE_WEAKENED=NO
PRODUCTION_MUTATION=0
```

Method for this reconciliation: read-only. Upstream identity was re-resolved
with `git ls-remote` (two tags) and PyPI JSON metadata was re-read for artifact
digests. No candidate package was installed, imported, or executed; no binary
wheel was downloaded; no third-party source was copied into this repository.

## Fresh-read basis

```text
CURRENT_MAIN=d031834954f13f946b5f335a9bb7f37bb79c1809
ASSIGNMENT_MAIN=d031834954f13f946b5f335a9bb7f37bb79c1809
ASSIGNMENT_MAIN_MATCHES_REMOTE=YES
PREDECESSOR_PR_2928=MERGED 3084f86ac59d1fa1d7049d13c2f43614f6b461a1
PREDECESSOR_PR_2932=MERGED b71e745b42139f369f3d877a5d109a9d0e98c99b
PREDECESSOR_PR_2934=MERGED 297eba97b4cbaf93b1dc1c969ab70050b31b4763
OPEN_PR_OVERLAP_ON_OSS_INTAKE_PATHS=NONE
```

The two predecessor delivery PRs landed after their `LOCAL must not merge`
stop-point was released by CENTRAL, so the audit artifacts and their contract
tests are already on current main. This child therefore reconciles existing
main state instead of re-delivering it.

## Immutable identity re-verification (read-only)

Both audits recorded immutable upstream identities. They were independently
re-resolved at reconciliation time; all four values still match.

| Field | Recorded (audit) | Re-resolved now | Match |
|---|---|---|---|
| pypdf tag object | `51f9c303af50fa0f55df7640f38e3df0239e8060` | `51f9c303af50fa0f55df7640f38e3df0239e8060` | YES |
| pypdf tag → commit | `d62cb58d3988b291b0435eddfd118c4f8f6b6a46` | `d62cb58d3988b291b0435eddfd118c4f8f6b6a46` | YES |
| Pillow tag → commit | `bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d` | `bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d` | YES |
| pypdf wheel sha256 | `7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14` | unchanged, size 395480 | YES |
| pypdf sdist sha256 | `bbc43aca292369ccc6cbc8a921991ecf2538a3587ab5a116eff06c321d647155` | unchanged, size 7033266 | YES |
| Pillow sdist sha256 | `3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce` | unchanged, size 47025035 | YES |

```text
PYPDF_TAG_OBJECT=51f9c303af50fa0f55df7640f38e3df0239e8060
PYPDF_UPSTREAM_COMMIT=d62cb58d3988b291b0435eddfd118c4f8f6b6a46
PILLOW_UPSTREAM_COMMIT=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d
PYPDF_WHEEL_SHA256=7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14
PYPDF_SDIST_SHA256=bbc43aca292369ccc6cbc8a921991ecf2538a3587ab5a116eff06c321d647155
PILLOW_SDIST_SHA256=3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce
FLOATING_REF_USED=NO
IMMUTABLE_PINS_PRESERVED=YES
PILLOW_WHEEL_COUNT_AT_RECONCILIATION=90
PYPI_YANKED_POLLED=NO  (both releases)
```

Per-candidate upstream identity as recorded by the audits:

```text
PYPDF_UPSTREAM_TAG_TYPE=ANNOTATED (tag object 51f9c303… points at d62cb58d…)
PILLOW_UPSTREAM_TAG_TYPE=LIGHTWEIGHT (tag is the commit bb1d8e8a… itself)
```

That asymmetry matters for the pinning strategy: for Pillow the tag name is
the only indirection, so the pin must always be cited as the commit, never as
"the 12.3.0 tag".

## pypdf 6.19.0 disposition

```text
CANDIDATE=candidate:pypdf
PACKAGE=pypdf
VERSION=6.19.0
LICENSE=BSD-3-Clause
IMMUTABLE_PIN=6.19.0

SOURCE_AUDIT_STATUS=SOURCE_AUDIT_PASS_WITH_RESTRICTIONS
SOURCE_AUDIT_ARTIFACT=docs/PYPDF_6_19_0_SOURCE_BEHAVIOR_AUDIT_2930.md
SOURCE_AUDIT_COMPLETE=YES

RUNTIME_ADOPTION_ELIGIBLE=NO
RUNTIME_ADOPTION=0
SKILL_REGISTRATION=0

REMAINING_PROVENANCE_GAPS=OPTIONAL_EXTRA_INTERNALS_NOT_ESTABLISHED; JBIG2DEC_BINARY_PROVENANCE_NOT_ESTABLISHED
OPTIONAL_DEPENDENCY_GAPS=DEFERRED_TRANSITIVE_AUDIT (cryptography, PyCryptodome, fonttools, Pillow, arabic-reshaper, python-bidi internals unaudited)
NATIVE_BINARY_GAPS=OPTIONAL_EXTRA_WHEELS_ONLY; CORE_WHEEL_IS_PURE_PYTHON (pypdf-6.19.0-py3-none-any.whl, sha256 recorded)
SUBPROCESS_POSTURE=PRESENT_CONDITIONAL_JBIG2DEC (argv list, no shell, PATH-resolved binary, fail-closed DependencyError when binary absent)
ENVIRONMENT_CREDENTIAL_POSTURE=CREDENTIAL_READS_ABSENT; CREDENTIAL_ENV_PROPAGATION=PRESENT_CONDITIONAL_JBIG2DEC (os.environ.copy() forwarded wholesale to the jbig2dec child)
NEXT_BOUNDED_DECISION=DECIDE_JBIG2DEC_SUBPROCESS_AUTHORITY_IN_PADIEM_WORKER (disable or bound child-env propagation) — verify with #3026
```

Load-bearing facts behind the restrictions:

- The only subprocess path in pypdf package source at this pin is the optional
  `jbig2dec` decoder (`filters.py`). It is reached only when a PDF stream is
  `/JBIG2Decode` and the binary resolves on `PATH`; otherwise the library raises
  `DependencyError` and no process starts.
- `os.environ.copy()` is passed to that child, so any host secret already in the
  worker environment would be inherited by an external process. No named
  credential variable is read or selected by pypdf, but the propagation itself
  is an authority expansion and must be bounded before adoption.
- On Python >= 3.11 the baseline wheel has zero required runtime dependencies.
  Optional extras are not installed by default; the pure-Python crypto fallback
  remains available.
- `RUNTIME_ADOPTION_ELIGIBLE=NO` is deliberate. A `SOURCE_AUDIT_PASS_WITH_RESTRICTIONS`
  is a source-behavior verdict only; eligibility additionally requires the
  jbig2dec decision, the extra-internals provenance, and the #2824 intake gate.

## Pillow 12.3.0 disposition

```text
CANDIDATE=candidate:pillow
PACKAGE=Pillow
VERSION=12.3.0
LICENSE=MIT-CMU
IMMUTABLE_PIN=12.3.0

SOURCE_AUDIT_STATUS=SOURCE_AUDIT_PASS_WITH_RESTRICTIONS
SOURCE_AUDIT_ARTIFACT=docs/PILLOW_12_3_0_SOURCE_AUDIT_2931.md
SOURCE_AUDIT_COMPLETE=YES

RUNTIME_ADOPTION_ELIGIBLE=NO
RUNTIME_ADOPTION=0
SKILL_REGISTRATION=0

REMAINING_PROVENANCE_GAPS=NATIVE_WHEEL_PROVENANCE_PENDING; NO_SLSA_ATTESTATION_VERIFIED; GH_RELEASE_ASSETS=0
OPTIONAL_DEPENDENCY_GAPS=None required (REQUIRED_RUNTIME_DEPENDENCIES=0); optional extras (icc/xmp/webp/aatranslate) unaudited but not adopted
NATIVE_BINARY_GAPS=8_C_EXTENSION_TARGETS (PIL._imaging, _imagingft, _imagingcms, _webp, _avif, _imagingtk, _imagingmath, _imagingmorph); 90 WHEEL_DIGESTS_RECORDED but not independently attested
SUBPROCESS_POSTURE=FORMAT_OR_API_GATED (gs only on the .eps default decode path; djpeg/ppmtogif/ppmquant opt-in or dead-by-default; Image.show()/ImageGrab explicit-API only; shell=True count 0, os.system count 1)
ENVIRONMENT_CREDENTIAL_POSTURE=CREDENTIAL_READS=NONE_FOUND; ENVIRONMENT_READS limited to PILLOW_* tuning at import, WINDIR/XDG_* font discovery, DISPLAY/WAYLAND_DISPLAY for ImageGrab
NEXT_BOUNDED_DECISION=ESTABLISH_NATIVE_WHEEL_PROVENANCE_FOR_THE_SELECTED_PLATFORM_WHEEL (or elect a source build) — verify with #3027
```

Additional Pillow facts that gate later decisions:

- `DECOMPRESSION_BOMB_PROTECTION=ENFORCED_DEFAULT` with
  `MAX_IMAGE_PIXELS_DEFAULT=89478485`; warning above 1x and hard error above 2x.
  Setting `MAX_IMAGE_PIXELS = None` disables the guard entirely.
- `MULTIFRAME_RESOURCE_RISK=UNCAPPED_FRAME_COUNT`: there is no global
  frame-count or total-pixels-across-frames budget, so per-frame bomb checks do
  not bound a multi-frame time/resource attack.
- `METADATA_BEHAVIOR=READ_WRITE_NO_AUTO_SANITIZATION`: EXIF/GPS/XMP/ICC are
  written back exactly as supplied, so PII stripping is a PADIEM-side duty.
- `.eps` is the one default-format path that shells out to an external tool.
- A source audit cannot certify binary artifacts. `NATIVE_BINARY_PROVENANCE_PENDING=YES`
  remains a separate gate from `SOURCE_AUDIT_PASS*`.

## Reconciliation effect on the canonical matrix

The #2925 matrix already carried `DEFERRED` with the gate receipt
`network_behavior_review_required` for both candidates, and its
`decision=DEFERRED (gate …): … source behavior audit is required before
adoption eligibility` text named exactly the gap these audits closed.

```text
MATRIX_PRIOR_OUTCOME_PYPDF=DEFERRED
MATRIX_PRIOR_OUTCOME_PILLOW=DEFERRED
MATRIX_ROWS_UNCHANGED=YES
MATRIX_DECISIONS_UNCHANGED=YES
DISPOSITION_CHANGED=NO
UPGRADE_FROM_DEFERRED=NO
```

Rationale for **not** flipping the rows to `ACCEPTED`:

- The canonical gate emits `ACCEPTED` / `REJECTED` only, and `ACCEPTED` is
  reserved in the matrix's own decision mapping for a candidate whose metadata,
  license **and** source behavior audit satisfy the gate. Neither candidate does:
  both carry an unresolved provenance/pre-authority gap
  (`NATIVE_WHEEL_PROVENANCE_PENDING` for Pillow; `jbig2dec` subprocess authority
  plus optional-extra internals for pypdf).
- Even a gate-`ACCEPTED` receipt would not be runtime adoption. The gate's
  receipt contract keeps `runtime_skill_registered=False` and
  `auto_runtime_registration=False` unconditionally, and `adoption_allowed`
  never means "Skill registered".
- The `test_oss_intake_matrix_2925.py` fixtures intentionally hold the
  metadata-only audit status (`audits_reviewed=False`) and assert the original
  `network_behavior_review_required` receipt. Moving those fixtures would
  require replacing metadata-level `UNKNOWN` audit values with real
  source-verified verdicts, which is a gate-level disposition change and
  therefore CENTRAL's decision, not this child's.

**This artifact adds the explicit reconciliation layer; it does not exercise
the disposition authority.**

## Remaining provenance gaps explicitly left UNKNOWN

```text
JBIG2DEC_BINARY_PROVENANCE=UNKNOWN
CRYPTOGRAPHY_INTERNALS=UNKNOWN
PYCRYPTODOME_INTERNALS=UNKNOWN
FONTTOOLS_INTERNALS=UNKNOWN
ARABIC_RESHAPER_INTERNALS=UNKNOWN
PYTHON_BIDI_INTERNALS=UNKNOWN
PILLOW_WHEEL_ATTESTATION=UNKNOWN
PILLOW_OPTIONAL_EXTRA_INTERNALS=UNKNOWN
UBUNTU_OR_WINDOWS_CODEC_LIBRARY_VERSIONS=UNKNOWN
FUTURE_RELEASES=UNAUDITED (any new tag requires a new audit)
```

No absence is inferred from package metadata, and no unknown is silently
promoted to PASS.

## Next bounded decisions

```text
NEXT_CHILD_PYPDF_JBIG2DEC_SUBPROCESS_AUTHORITY=#3026
NEXT_CHILD_PILLOW_NATIVE_WHEEL_PROVENANCE=#3027
```

These are the two decisions that actually sit in front of PDF and Image Skill
adoption. In both cases the bounded question is the same shape: not "is the
library good", but "which authority does the PADIEM worker acquire, and can it
be bounded". For pypdf that is one conditional external process and its
environment inheritance; for Pillow that is one platform's native binary that a
source audit cannot certify.

## Acceptance

```text
PYPDF_AUDIT_RECONCILED=YES
PILLOW_AUDIT_RECONCILED=YES
IMMUTABLE_PINS_PRESERVED=YES
RESTRICTIONS_PRESERVED=YES
UNKNOWN_REMAINS_UNKNOWN=YES
RUNTIME_ADOPTION=0
GATE_WEAKENED=NO
NEXT_DECISIONS_EXPLICIT=YES
```

CENTRAL owns any change to candidate disposition in
`OSS_CANDIDATE_INTAKE_MATRIX_2925.md`. This document does not claim readiness,
does not register a Skill, and does not approve runtime adoption.
