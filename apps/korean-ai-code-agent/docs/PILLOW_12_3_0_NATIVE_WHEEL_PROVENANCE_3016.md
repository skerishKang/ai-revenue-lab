# Pillow 12.3.0 native-wheel provenance gate — Issue #3016

Refs: #3016 · Parent: #2823 · Program: #2821 · Image Skill: #2828  
Predecessors: #2931, #2990, #3012  
Fresh-read basis: `origin/main=070ceee351bf8ce07bfa119f0fc268cc342df18c`

## Scope and non-equivalence

This is a source-only provenance decision. It does not install, download, import,
execute, or register Pillow, and it does not implement the Image Skill. The
canonical OSS intake gate, file intake safety gate, parser isolation boundary,
Skill registry, and artifact provenance contracts remain the authorities.

```text
PILLOW_PROVENANCE_DECISION=PLATFORM_SPECIFIC_ACCEPTANCE_REQUIRED
RUNTIME_ADOPTION=0
MATRIX_ADOPTION_CHANGE=0
SECOND_PROVENANCE_AUTHORITY=0
```

The decision is deliberately narrower than “PyPI is safe” and broader than
“source builds are safe.” Official wheels are hash-pinnable and platform-tagged,
but native-binary provenance is not established merely by publication on PyPI.
A future adopter must verify the selected wheel's release-specific provenance
and bind the exact artifact receipt before any runtime decision.

## Immutable identity

```text
PACKAGE=Pillow
VERSION=12.3.0
UPSTREAM_REPOSITORY=https://github.com/python-pillow/Pillow
UPSTREAM_TAG=12.3.0
UPSTREAM_TAG_TYPE=LIGHTWEIGHT
UPSTREAM_TAG_OBJECT=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d
UPSTREAM_COMMIT=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d
LICENSE=MIT-CMU
PYPI_PROJECT=Pillow
PYPI_SDIST_FILENAME=pillow-12.3.0.tar.gz
PYPI_SDIST_SHA256=3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce
PYPI_RELEASE_UPLOAD_DATE=2026-07-01
PYPI_RELEASE_YANKED=NO
FLOATING_REF_USED=NO
```

The PyPI 12.3.0 JSON release record contains one sdist and 86 wheels (87 total
artifacts). All recorded artifacts were reported as unyanked. The existing
#2931 audit recorded 90 wheel digests from an earlier snapshot; this fresh
PyPI record is the current artifact-count authority for this issue and the
difference is preserved rather than silently normalized.

## Native-wheel supply-chain findings

```text
OFFICIAL_WHEEL_EXISTS=YES
OFFICIAL_WHEEL_ORIGIN=PYPI_PROJECT_Pillow_12.3.0_OFFICIAL_RELEASE
WHEEL_HASH_PINNABLE=YES
WHEEL_PLATFORM_EXPLICIT=YES_IN_WHEEL_FILENAME
WHEEL_ABI_EXPLICIT=YES_IN_WHEEL_FILENAME

BUNDLED_NATIVE_LIBRARIES_PRESENT=YES_PER_RELEASE_WHEEL
SYSTEM_NATIVE_LIBRARIES_REQUIRED=NO_FOR_REVIEWED_OFFICIAL_WHEEL; YES_IF_SOURCE_BUILD
DYNAMIC_NATIVE_LOADING_PRESENT=YES
EXTERNAL_PROCESS_EXECUTION=FORMAT_OR_API_GATED
NETWORK_AUTHORITY_GAINED=NO_IN_CORE
RAW_HOST_ENV_INHERITANCE=NO_RUNTIME_PROCESS
WHEEL_INSTALL_IMPLICITLY_FETCHES_RUNTIME_BINARY=NO
```

PyPI wheel filenames encode the Python, ABI, and platform tags. The release
matrix includes CPython, free-threaded CPython, PyPy, macOS, manylinux, musllinux,
Windows, and iOS variants. Platform selection is therefore mandatory; an
unqualified “Pillow 12.3.0 wheel” is not an acceptable receipt.

The wheel is native: Pillow 12.3.0 builds C extensions including `_imaging`,
`_imagingft`, `_imagingcms`, `_webp`, `_avif`, `_imagingtk`, `_imagingmath`, and
`_imagingmorph`. Native codec/dependency posture varies by wheel and build
configuration. The pinned Pillow wheel workflow builds platform-specific wheels
with cibuildwheel, uses platform-specific build environments, embeds a generated
CycloneDX SBOM, and publishes through the pinned pypa action with
`attestations: true` configured. This audit did not fetch and verify a
release-specific attestation or bind an SBOM to a selected wheel, so those facts
remain a future receipt precondition rather than an acceptance claim.

```text
UPSTREAM_WHEEL_WORKFLOW_PINNED=YES
UPSTREAM_WHEEL_WORKFLOW_SBOM=EMBEDDED
UPSTREAM_PUBLISH_ATTESTATIONS_CONFIGURED=YES
RELEASE_SPECIFIC_ATTESTATION_VERIFIED_BY_THIS_AUDIT=NO
RELEASE_SPECIFIC_SBOM_VERIFIED_BY_THIS_AUDIT=NO
GH_RELEASE_ASSETS_RECORDED_BY_PRIOR_AUDIT=0
```

Pillow runtime source behavior remains bounded by #2931: ordinary PNG/JPEG/GIF/
BMP/TIFF/WebP/AVIF operations do not invoke external programs, while EPS decode
uses Ghostscript, `Image.show()` uses external viewers, and `ImageGrab` uses
platform screenshot/clipboard helpers. These are format/API-gated behavior, not
a blanket runtime permission. Dynamic loading includes optional platform paths
such as FriBiDi/Tk/User32; codecs are otherwise linked at build time.

## Platform decision

```text
WINDOWS_X64=RECEIPT_REQUIRED_BEFORE_ACCEPTANCE
LINUX_X64=RECEIPT_REQUIRED_BEFORE_ACCEPTANCE
MACOS_ARM64=RECEIPT_REQUIRED_BEFORE_ACCEPTANCE
OTHER_OR_UNREVIEWED_PLATFORM=REJECT
```

No platform is accepted by this source-only child. The next runtime authority,
if separately authorized, may accept only one exact artifact per platform and
Python ABI. This decision does not choose a platform for PADIEM.

## Required wheel receipt

For any future selected platform wheel, the receipt must contain all fields:

```text
PACKAGE=Pillow
VERSION=12.3.0
WHEEL_FILENAME=
PYTHON_TAG=
ABI_TAG=
PLATFORM_TAG=
SHA256=
SOURCE_RELEASE_REF=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d
LICENSE=MIT-CMU
NATIVE_BINARY_POSTURE=
RELEASE_SPECIFIC_ATTESTATION=
RELEASE_SPECIFIC_SBOM=
FLOATING_VERSION=NO
UNHASHED_WHEEL=NO
UNREVIEWED_PLATFORM=NO
```

Acceptance requires: official PyPI origin, exact filename/tag match, exact
SHA-256 match, immutable upstream commit/ref, selected platform explicitly
supported by the receipt, native binary posture reviewed, and release-specific
provenance evidence attached or linked. A receipt for one platform/ABI does not
transfer to another.

## Source-build comparison

A source build is not automatically more trustworthy than a pinned official
wheel. It changes the trust surface from the publisher's wheel pipeline to the
compiler, headers, native libraries, build flags, environment, and output digest.

```text
SOURCE_BUILD_REQUIRES_COMPILER=YES
SOURCE_BUILD_REQUIRES_SYSTEM_HEADERS=YES_FOR_NATIVE_CODECS
SOURCE_BUILD_NATIVE_DEPENDENCY_DISCOVERY=YES_ENVIRONMENT_AND_PATH_SENSITIVE
SOURCE_BUILD_ENVIRONMENT_SENSITIVE=YES
SOURCE_BUILD_REPRODUCIBLE_BY_DEFAULT=NO
```

Official build documentation requires a compiler toolchain (including Visual
Studio/NASM on Windows or equivalent Unix toolchains), Python development
libraries, and native libraries/headers such as zlib, libjpeg, libtiff,
FreeType, LittleCMS, libwebp, OpenJPEG, optional libraqm/FriBiDi, libimagequant,
libxcb, and libavif depending on requested features. Build options can enable,
disable, or vendor features; those choices materially change the native
artifact. A controlled source build therefore needs its own pinned compiler,
dependency versions, flags, environment, output wheel hash, and build receipt.
It is a fallback election, not a free safety upgrade.

## Required negative cases

```text
UNPINNED_PILLOW_VERSION=REJECT
UNKNOWN_WHEEL_FILENAME=REJECT
UNKNOWN_PLATFORM_TAG=REJECT
UNKNOWN_ABI_TAG=REJECT
HASH_MISMATCH=REJECT
NON_OFFICIAL_ORIGIN=REJECT
UNSUPPORTED_PLATFORM=REJECT
MISSING_PROVENANCE_RECEIPT=REJECT
FLOATING_LATEST=REJECT

UNPINNED_COMPILER=REJECT
UNPINNED_NATIVE_DEPENDENCY=REJECT
UNRECORDED_BUILD_FLAGS=REJECT
MISSING_OUTPUT_HASH=REJECT
```

## Safety counters

```text
PIP_INSTALL=0
PILLOW_IMPORT=0
PILLOW_RUNTIME_EXECUTION=0
IMAGE_RUNTIME_REGISTRATION=0
IMAGE_SKILL_REGISTRATION=0
THIRD_PARTY_SKILL_EXECUTION=0
PROVIDER_CALL=0
NETWORK_PROVIDER_CALL=0
SECRET_VALUE_READ=0
SECRET_MUTATION=0
PRODUCTION_DEPLOY=0
PRODUCTION_MUTATION=0
MATRIX_ADOPTION_CHANGE=0
GATE_WEAKENED=NO
RUNTIME_ADOPTION=0
```

## Disposition

```text
SOURCE_ADVANCE_JUSTIFIED=YES
PILLOW_PROVENANCE_DECISION=PLATFORM_SPECIFIC_ACCEPTANCE_REQUIRED
RUNTIME_ADOPTION=0
DRAFT_ONLY=YES
READY=NO
MERGE=NO
STOP_AND_WAIT_FOR_CENTRAL=YES
```

CENTRAL owns any later matrix disposition, platform election, receipt approval,
runtime composition, or Image Skill implementation.
