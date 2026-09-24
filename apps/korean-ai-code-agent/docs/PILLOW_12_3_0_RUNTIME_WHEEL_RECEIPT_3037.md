# Pillow 12.3.0 runtime wheel receipt and image foundation — Issue #3037

Refs: #3037 · Predecessors: #3016 (source-only provenance gate), #2990, #2931
Base for this work: `origin/main=4a4afc4cee0324b69e08d8a325ac5467addf2448`

This is the *runtime* receipt contract that #3016 required before Pillow could
be accepted on any platform. It is a **separate, additive** document. #3016,
#2931, #2990 and the canonical OSS intake matrix are unchanged; no source-only
history is rewritten, normalized, or retold as if it had authorized a runtime.

```text
ISSUE=3037
DOCUMENT_TYPE=RUNTIME_WHEEL_RECEIPT_AND_IMAGE_FOUNDATION
PREDECESSOR_SOURCE_ONLY_DECISION=#3016
PRESERVES_3016_HISTORY=YES
SECOND_PROVENANCE_AUTHORITY=0
SECOND_SKILL_REGISTRY=0
PADIEM_MATRIX_EDITED=0
SOURCE_ONLY_DECISION_REVERSED=NO
```

## Non-equivalence

```text
#3016_SOURCE_ONLY_DECISION != #3037_RUNTIME_RECEIPT
#3016 = platform-specific acceptance is REQUIRED
#3037 = here are the two exact artifacts, and here is the code that consumes them
#2931_SOURCE_AUDIT != RUNTIME_ADOPTION
#2990_RECONCILIATION != RUNTIME_ADOPTION
RUNTIME_ADOPTION=2_PLATFORMS_1_ARTIFACT_EACH
FLOATING_VERSION=NO
FLOATING_LATEST=REJECT
```

The machine-readable form of this document is
`packages/padiem-ai-core/padiem_ai_core/pillow_wheel_receipts.py`. The prose
here and that module are two views of one contract; the module is what CI reads
and what the tests assert, so a workflow cannot silently drift from the receipt.

## Immutable release identity

```text
PACKAGE=Pillow
VERSION=12.3.0
UPSTREAM_REPOSITORY=https://github.com/python-pillow/Pillow
UPSTREAM_TAG=12.3.0
UPSTREAM_TAG_TYPE=LIGHTWEIGHT
UPSTREAM_TAG_OBJECT=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d
UPSTREAM_COMMIT=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d
SOURCE_RELEASE_REF=https://github.com/python-pillow/Pillow/releases/tag/12.3.0
PYPI_SDIST_SHA256=3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce
LICENSE=MIT-CMU
LICENSE_FILE=https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/LICENSE
LICENSE_LINKAGE=COMMIT_PINNED_UPSTREAM_LICENSE_FILE; SAME_LICENSE_ID_AS_MATRIX_ROW
```

The license linkage is two-sided and both sides are recorded: the SPDX-style
identifier `MIT-CMU` is the value already published in
`OSS_CANDIDATE_INTAKE_MATRIX_2925.md`, and the grant text is read from the
upstream `LICENSE` file at the pinned commit rather than from a floating branch
reference. #3016 recorded the same license; this receipt adds the commit-pinned
file link.

## Approved receipts

Exactly two artifacts are approved: CPython 3.12 on Windows x64 and CPython 3.12
on Linux x64. Both come from the official PyPI file origin. A receipt does not
transfer to another interpreter, ABI, architecture or platform.

```text
WINDOWS_X64_RECEIPT_ID=cp312/win_amd64
WINDOWS_X64_WHEEL_FILENAME=pillow-12.3.0-cp312-cp312-win_amd64.whl
WINDOWS_X64_PYTHON_TAG=cp312
WINDOWS_X64_ABI_TAG=cp312
WINDOWS_X64_PLATFORM_TAG=win_amd64
WINDOWS_X64_SHA256=a2b55dd6b2a4c4b7d87ffa56bdb33fdc5fdb9a462173861a7bc097f17d91cb09
WINDOWS_X64_SIZE_BYTES=7227137
WINDOWS_X64_URL=https://files.pythonhosted.org/packages/45/89/da2f7971a317f83d807fdd4065c0af40208e59e692cc43d315a71a0e96d1/pillow-12.3.0-cp312-cp312-win_amd64.whl
WINDOWS_X64_UPLOAD_TIME=2026-07-01T11:54:22.025716Z
WINDOWS_X64_YANKED=NO
WINDOWS_X64_REQUIRES_PYTHON=>=3.10

LINUX_X64_RECEIPT_ID=cp312/manylinux_2_27_x86_64.manylinux_2_28_x86_64
LINUX_X64_WHEEL_FILENAME=pillow-12.3.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
LINUX_X64_PYTHON_TAG=cp312
LINUX_X64_ABI_TAG=cp312
LINUX_X64_PLATFORM_TAG=manylinux_2_27_x86_64.manylinux_2_28_x86_64
LINUX_X64_SHA256=78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91
LINUX_X64_SIZE_BYTES=6940830
LINUX_X64_URL=https://files.pythonhosted.org/packages/84/21/a35af28dcc61f37ed850a2d64c65c701321dfbf25085e469d5559360cbbf/pillow-12.3.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
LINUX_X64_UPLOAD_TIME=2026-07-01T11:54:13.732453Z
LINUX_X64_YANKED=NO
LINUX_X64_REQUIRES_PYTHON=>=3.10

WHEEL_ORIGIN_FOR_BOTH=https://files.pythonhosted.org
NON_OFFICIAL_ORIGIN=REJECT
OTHER_OR_UNREVIEWED_PLATFORM=REJECT
```

## Native-library posture

```text
NATIVE_BINARY_POSTURE=COMPILED_EXTENSIONS_WITH_BUNDLED_THIRD_PARTY_CODECS
EXTENSIONS_BUNDLED=_imaging;_imagingft;_imagingcms;_webp;_avif;_imagingmath;_imagingmorph
BUNDLED_CODEC_LIBRARIES=zlib;libjpeg;libtiff;FreeType;LittleCMS;libwebp;OpenJPEG;libavif
LINK_MODEL=BUILD_TIME_LINKED; OPTIONAL_PLATFORM_PATHS_REMAIN_DYNAMIC (FriBiDi,Tk,User32)
SYSTEM_NATIVE_LIBRARIES_REQUIRED=NO_FOR_THESE_TWO_RECEIPTS
SOURCE_BUILD_FALLBACK_ALLOWED=NO
EXTERNAL_HELPER_EXECUTION=NEVER_CALLED_BY_CORE_IMAGE_HELPERS
EPS_DECODE_PATH=UNSUPPORTED; Ghostscript=NEVER_INVOKED
ImageShow_CALLED=NO
ImageGrab_CALLED=NO
LOAD_TRUNCATED_IMAGES_ENABLED=NO
NETWORK_CALLS=0
PROVIDER_CALLS=0
OCR=0
VISION_INFERENCE=0
HOST_FILESYSTEM_READ=0
HOST_FILESYSTEM_WRITE=0
```

Pillow is a native extension package, so the trust surface of a wheel is the
wheel's own binaries. That is exactly why the artifact is pinned by digest and
size rather than by version range, and why a source build is not treated as a
safer fallback. The `#3016` source-build comparison stands unchanged: a build
would need its own pinned toolchain, headers, dependency versions, flags,
environment, output digest and build receipt.

## Explicitly not verified

This is stated so no reader can mistake absence of a check for a passed check.

```text
RELEASE_SPECIFIC_ATTESTATION_VERIFIED=NO
RELEASE_SPECIFIC_ATTESTATION_NOTE=Wheel was NOT fetched, parsed and bound to a
  release-specific PEP 740 attestation. Acceptance rests on the official PyPI
  origin plus the exact recorded filename, size and SHA-256.
RELEASE_SPECIFIC_SBOM_VERIFIED=NO
RELEASE_SPECIFIC_SBOM_NOTE=No SBOM was fetched or bound to either wheel. Upstream
  is recorded as embedding a generated SBOM in its wheel build, but that is an
  upstream build claim and was not confirmed for these two artifacts.
GH_RELEASE_ASSETS_VERIFIED=NO
```

## Runtime adoption

```text
DEPENDENCY_NAME=Pillow
DEPENDENCY_PIN=12.3.0
DEPENDENCY_SPEC=EXACT_EQUALS; NO RANGE; NO LOWER BOUND; NO latest/compatible
KAGENT_DEPENDENCY_SURFACE=apps/korean-ai-code-agent/pyproject.toml
WHEEL_ONLY_ADOPTION=YES
SOURCE_BUILD_FALLBACK=NO
PILLOW_RESOLUTION_DURING_DEPENDENCY_INSTALL=DISABLED
LOCAL_VERIFIED_WHEEL_INSTALLED_BEFORE_DEPENDENCY_INSTALL=YES
INSTALLED_ARTIFACT_PROOF=PIL.__version__ + platform tag + wheel filename recorded in CI output
CI_PYTHON_VERSION=3.12
CI_PLATFORMS=ubuntu-latest; windows-latest
```

CI resolves nothing about Pillow at dependency-install time. It selects the one
approved receipt for its platform, downloads exactly that URL, verifies
filename + size + SHA-256 before any installer runs, installs the verified local
wheel with `--no-deps --no-index`, and only then installs KAgent and the
monorepo dependencies. A floating, ranged, or `latest`-compatible dependency is
rejected.

Pillow is declared directly in the KAgent dependency surface as
`Pillow==12.3.0`; the exact wheel is installed and verified before that
dependency is resolved. The base Core install does not silently acquire a
native binary.

## Image foundation contract

`packages/padiem-ai-core/padiem_ai_core/image_helpers.py` is a product-neutral
helper, not a Skill and not a registry. `kagent.image_skill` is a thin facade
over it that always runs the existing `inspect_file(filename, payload)` gate
first.

```text
HELPER_SURFACE=inspect_image; transform_image; sanitize_metadata; thumbnail_image
INPUT_FORMATS=PNG;JPEG;WEBP;GIF
OUTPUT_FORMATS=PNG;JPEG;WEBP
RESERVED_CAPABILITY_IDS_REUSED=image.inspect; image.transform
NEW_CAPABILITY_IDS=0
NEW_SKILL_REGISTRY=0
REGISTRATION_BY_THIS_CHANGE=0

MAX_IMAGE_BYTES=16777216
MAX_IMAGE_PIXELS=40000000
MAX_OUTPUT_BYTES=8388608
MAX_INSPECT_FRAMES=64
TRANSFORM_ORDER=EXIF_ORIENTATION_THEN_ROTATE_THEN_CROP_THEN_RESIZE
ALPHA_POSTURE=PRESERVED_RGBA_FOR_PNG_AND_WEBP
JPEG_ALPHA_POSTURE=COMPOSITED_ONTO_FIXED_MATTE_RGB_255_255_255
METADATA_SANITATION_DEFAULT=REMOVE_EXIF_GPS_XMP_TEXT
METADATA_PRESERVE_ICC_OPTION=COPIES_ONLY_A_VALID_BOUNDED_ICC; STILL_REMOVES_ALL_OTHER_METADATA
ENCODER_SETTINGS=DETERMINISTIC_CONSTANTS (JPEG quality 90, subsampling 0,
  non-progressive, non-optimized; WEBP quality 80 method 6 lossless=0;
  PNG compress_level 6 optimize=0)
DETERMINISM=SAME_INPUT_AND_ARGUMENTS_PRODUCE_SAME_OUTPUT_BYTES
```

Static-frame semantics are deterministic and explicit: `inspect_image` may
*report* a multi-frame container within a hard frame bound, and
`transform_image` / `thumbnail_image` **refuse** anything with more than one
frame. A caller can therefore never silently receive the first frame of an
animation.

### Fail-closed codes

Every refusal is one stable string. Raw Pillow exceptions never escape.

```text
IMAGE_BYTES_INVALID
IMAGE_BYTES_OVERSIZED
IMAGE_FORMAT_UNSUPPORTED
IMAGE_PIXELS_EXCEEDED
IMAGE_DECOMPRESSION_BOMB
IMAGE_DECODE_FAILED
IMAGE_FRAME_COUNT_EXCEEDED
IMAGE_MULTIFRAME_REFUSED
IMAGE_METADATA_UNREADABLE
IMAGE_CROP_INVALID
IMAGE_RESIZE_INVALID
IMAGE_ROTATE_INVALID
IMAGE_OUTPUT_FORMAT_UNSUPPORTED
IMAGE_OUTPUT_PIXELS_EXCEEDED
IMAGE_OUTPUT_BYTES_EXCEEDED
```

Bounds are checked before the work that could exhaust memory, not after. A
metadata parse failure is reported as a failure; it is never downgraded to "no
metadata present".

### Negative cases

```text
OVERSIZED_INPUT_BYTES=REJECT
OVERSIZED_PIXELS=REJECT
OVERSIZED_OUTPUT_BYTES=REJECT
DECOMPRESSION_BOMB=REJECT
MALFORMED_OR_CORRUPT_INPUT=REJECT
TRUNCATED_INPUT=REJECT
UNSUPPORTED_FORMAT=REJECT
INVALID_CROP_RECTANGLE=REJECT
NONPOSITIVE_RESIZE=REJECT
UNEXPECTED_MULTIFRAME_TRANSFORM=REJECT
METADATA_PARSE_FAILURE=REJECT
EPS_INPUT=REJECT
UNKNOWN_PLATFORM_WHEEL=REJECT
HASH_MISMATCH=REJECT
SIZE_MISMATCH=REJECT
FILENAME_MISMATCH=REJECT
YANKED_ARTIFACT=REJECT
PILLOW_SOURCE_BUILD=REJECT
PILLOW_FLOATING_SPEC=REJECT
```

## Non-goals and preserved boundaries

```text
HWPX_FILES_MODIFIED=0        (#3034)
CONTROL_PLANE_FILES_MODIFIED=0  (#3035)
PDF_PARSER_FILES_MODIFIED=0  (#3036)
KAGENT_IMAGE_OCR=NOT_IMPLEMENTED  (image.ocr stays reserved and unused)
IMAGE_TO_PDF=NOT_IMPLEMENTED
EPS_SUPPORT=NO
PRODUCTION_DEPLOY=0
PRODUCTION_MUTATION=0
DRAFT_ONLY=YES
READY=NO
MERGE=NO
```

## Disposition

```text
RUNTIME_RECEIPT_RECORDED=YES
APPROVED_ARTIFACTS=2
UNREVIEWED_PLATHS_APPROVED=0
RUNTIME_ADOPTION=YES_UNDER_THIS_RECEIPT
SECOND_PROVENANCE_AUTHORITY=0
SECOND_SKILL_REGISTRY=0
DRAFT_ONLY=YES
READY=NO
MERGE=NO
```

An independent Local Validation run against a reviewed head, in the real
target environment, remains outstanding and is a merge precondition under the
repository operating policy.
