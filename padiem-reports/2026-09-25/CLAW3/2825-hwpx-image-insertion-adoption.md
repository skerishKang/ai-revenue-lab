# CLAW3 #2825 HWPX Image Insertion Technology Scan

## Decision

```text
MODE=HWPX_IMAGE_INSERTION_TECH_SCAN_AND_CONDITIONAL_CLOSURE
ISSUE=#2825
PARENT=#2821
DEPENDENCY=#2826 remains blocked behind #2825
WORKTREE=E:/padiem-clawu-260925-2825-tech-scan
BASELINE=a1d0164d385312d2c75914359dea26a5daa76afa
SEARCH_BEFORE_BUILD=YES
IMPLEMENTATION_STARTED=YES
SOURCE_ADVANCE_JUSTIFIED=YES_PNG_CANONICAL_ONLY
TECH_SCAN=ACCEPTED
INPUT_IMAGE_TYPES=PNG;JPEG
HWPX_EMBEDDED_IMAGE_FORMAT=PNG_ONLY
HWPX_EMBEDDED_MEDIA_TYPE=image/png
DIRECT_JPEG_EMBED=DEFERRED
SECOND_HWPX_AUTHORITY=0
SECOND_IMAGE_DECODER=0
READY=NO
MERGE=NO
ISSUE_CLOSE=NO
PROVIDER_CALL=0
PRODUCTION_MUTATION=0
```

The scan found a credible implementation candidate and strong read-side grammar evidence, but not a complete authoritative write-side contract suitable for unconditional source advancement. The remaining gaps are material: the exact JPEG MIME authority is unresolved (`image/jpeg` in the candidate versus `image/jpg` in a real Hancom-style fixture), the golden fixture is a pinned hwpxlib corpus artifact rather than a first-party Hancom-produced fixture, and the candidate's Hancom render report is self-reported upstream evidence that has not been independently reproduced in this environment.

## Candidate shortlist

### 1. airmang/python-hwpx v6.5.0

```text
UPSTREAM=https://github.com/airmang/python-hwpx
PINNED_COMMIT=d22da20044422f9dcd5d682cf372fb492e9289e9
LICENSE=Apache-2.0
RUNTIME=Python >=3.10; lxml>=4.9,<7
ADOPTION_MODE=BOUNDED_ADAPTATION_CANDIDATE
CLOUD_FEASIBILITY=YES, subject to dependency intake
WINDOWS_LINUX=YES, source-level
HIGH_FIDELITY_EVIDENCE=5/5 authored-picture render checks reported against Hancom Office HWP.app on macOS
PRODUCTION_ADOPTION=0 pending intake and unresolved authority gaps
```

Direct source inspection confirms `add_image()`/`add_picture()` behavior: deterministic `BIN####` allocation, collision rejection for explicit IDs, `BinData/<id>.<fmt>` package members, `content.hpf` manifest mutation, `isEmbeded="1"`, `binaryItemIDRef`, HWPUNIT sizing, and package validation. The five focused image workflow tests passed in an isolated environment after installing the exact checkout and `lxml` 6.1.3. The tests are source-level, not an independent Hancom oracle.

### 2. martiniifun/pyhwpx v1.7.2

```text
UPSTREAM=https://github.com/martiniifun/pyhwpx
PINNED_COMMIT=a83b782673ecf49e18964610edea1d12c23b7f09
LICENSE=MIT
RUNTIME=Windows COM/Hancom desktop automation
ADOPTION_MODE=SIDECAR_ORACLE
CLOUD_FEASIBILITY=NO for normal cloud path
WINDOWS_LINUX=WINDOWS only; Hancom desktop required
HIGH_FIDELITY_EVIDENCE=Hancom automation surface, but no independent BinData MIME/ID contract
PRODUCTION_ADOPTION=0
```

Useful as a high-fidelity Windows sidecar or oracle, not as the default Claw Cloud engine. Import-time COM cache behavior and possible network download behavior require separate isolation review.

### 3. Hancom HWP SDK

```text
UPSTREAM=https://www.hancom.com/en/product/sdk/hwpSdk
LICENSE=COMMERCIAL
RUNTIME=vendor SDK
ADOPTION_MODE=COMMERCIAL
CLOUD_FEASIBILITY=UNRESOLVED
WINDOWS_LINUX=UNRESOLVED
HIGH_FIDELITY_EVIDENCE=vendor claims HWP/HWPX open/create/save and image insertion
PRODUCTION_ADOPTION=0
```

Potential authoritative commercial path, but public material does not establish hosted multi-tenant rights, Linux/server packaging, pricing, or template-preservation guarantees. Written vendor confirmation is required before treating it as an approved backend.

## Authoritative image grammar evidence

### Proven read-side facts

Official Hancom `hwpx-owpml-model` at commit `1453388472c703a4b299a0834f425cdac16644b9` establishes the read chain:

```text
hp:pic -> hc:img/@binaryItemIDRef
      -> content.hpf opf:manifest opf:item/@id
      -> opf:item/@href
      -> package member
```

The official model also derives the extension from the manifest `media-type` suffix. It does not implement a new-image ID allocator; duplicate IDs are not collision-safe.

The official Hancom article provides a first-party PNG example using `image/png`, `BinData/image1.PNG`, and `isEmbeded="1"`. The existing repository's canonical parser already has the correct read authority and must remain the only Core HWPX parser.

### Candidate facts

The candidate source provides:

```text
jpg/jpeg -> image/jpeg
png      -> image/png
member   -> BinData/<id>.<extension>
id       -> deterministic BIN0001, BIN0002, ...
picture  -> hc:img/@binaryItemIDRef
embedded -> opf:item/@isEmbeded="1"
```

The candidate's collision scan covers existing image manifest IDs, BinData manifest hrefs/stems, and actual BinData package members. This is useful evidence, but it is not a substitute for an independent format authority.

### Unresolved authority conflict

The pinned real-looking `SimplePicture.hwpx` fixture contains:

```text
manifest media-type=image/jpg
member=BinData/image1.jpg
picture binaryItemIDRef=image1
```

The candidate writes `image/jpeg`. The source tree therefore proves that both spellings occur in the available evidence, not which spelling is canonical for new JPEG output. The implementation gate must not silently choose one. A bounded policy may later normalize to the candidate's standards-compliant `image/jpeg` only after an explicit compatibility decision and a real Hancom reopen/render test for both accepted forms.

## Golden fixture provenance

Fixture:

```text
E:/padiem-hwpx-2825-research/python-hwpx/tests/fixtures/hwpxlib_corpus/reader_writer__SimplePicture.hwpx
SIZE=79447
SHA256=7ed3bdf89986fd88fdbcd92eaeac3f852aa6984fb1f7ddf4dd4f582afe20084c
IMAGE_MEMBER=BinData/image1.jpg
IMAGE_SHA256=09f07029707021fe39f031f2e5ec4fd91617bf5b92d26ddefc0d4335164bcad9
VERSION_XML=HCFVersion 5.0.5; Hancom Office Hangul 9.1.1 build 5656 WIN32LE
SOURCE_REPO=https://github.com/neolord0/hwpxlib
SOURCE_PIN=3bbaaa90bdb1f14c58fd2f87c80105bc8fd37473
SOURCE_PATH=testFile/reader_writer/SimplePicture.hwpx
FIXTURE_INTRO_COMMIT=5b4f0050a41ba638fbaefcb5b687e5436a7a7a1a
```

The fixture is vendored by the candidate under Apache-2.0 corpus attribution. It is a strong read-side structural fixture and proves a real package shape, including `META-INF/container.xml`, `Contents/content.hpf`, the picture subtree, and an embedded JPEG. It does not prove first-party production authority for the `image/jpg` spelling, and it has no independent reopen receipt attached in the fixture metadata.

## Reproduction evidence

Isolated environment:

```text
PYTHON=C:/Users/limone/.workbuddy-ai/binaries/python/envs/hwpx2825/Scripts/python.exe
PACKAGE=python-hwpx 6.5.0 editable checkout at pinned commit
LXML=6.1.3
PYTEST=8.4.2
```

Smoke import and document creation passed. Focused test file result:

```text
tests/test_image_object_workflow.py: 5 passed, 3 deprecation warnings
```

Covered by the focused tests: deterministic `BIN0001`, package member creation, manifest linkage, `isEmbeded`, package validation, replacement graph integrity, dangling reference detection, and orphan BinData detection. The candidate test suite does not independently prove real Hancom reopen/render for the generated outputs.

## Bounded contract plan (not implemented)

The eventual Core/KAgent slice should accept only structured, bounded data, never raw XML or caller-selected package paths:

```text
REQUEST={image_bytes, image_format, width, height, unit}
IMAGE_FORMAT={png,jpeg}
UNIT={HWPUNIT,mm}
MAX_IMAGE_BYTES=<explicitly derived Core bound, below package limits>
MAX_PACKAGE_BYTES=existing 2 MiB document bound
```

The operation should:

1. Run existing #2824 intake and Core image inspection/transform.
2. Validate the HWPX package with the existing archive gate.
3. Parse only through the existing canonical HWPX reader.
4. Derive the next unused `BIN####` ID from all authoritative and package-visible image ID sources.
5. Add the canonical `BinData/<id>.<ext>` member.
6. Add/update `content.hpf` manifest and `header.xml` bin item through the single existing package authority.
7. Add the picture paragraph using the established `hp:pic`/`hc:img`/`binaryItemIDRef` grammar and explicit HWPUNIT dimensions.
8. Preserve unrelated members and template XML byte-for-byte where mutation is additive and structurally safe.
9. Re-enter the existing archive validator and canonical parser.
10. Return a readback receipt containing the allocated ID, member path, MIME, dimensions, and validation result.

Fail closed for unknown formats, malformed PNG/JPEG, existing ID collisions, unsupported XML/package variants, package-size overflow, and any request requiring caller-provided raw XML, relationship IDs, namespace IDs, shape IDs, style IDs, or ZIP member paths.

## Required next provenance children

1. Obtain an independently reproducible real-Hancom reopen/render receipt for generated PNG and JPEG outputs, including both candidate MIME spellings if compatibility requires it.
2. Obtain first-party or standards-document authority for the JPEG `media-type` spelling and `isEmbeded` spelling.
3. Complete OSS intake for `python-hwpx` and `lxml`, preserving Apache-2.0 NOTICE/attribution obligations.
4. Verify exact dependency wheel provenance and reproducibility.
5. Only then decide whether a minimal bounded adaptation can be implemented without creating a second parser or serializer authority.

## Implementation closure addendum

The accepted PNG-canonical slice is now implemented and published as a Draft PR.

```text
IMPLEMENTATION_COMMIT=835a4f1338093aa73ad6b0f8775c38169f2b0daa
DRAFT_PR=https://github.com/skerishKang/ai-revenue-lab/pull/3079
DRAFT_PR_STATE=OPEN_DRAFT
FINAL_IMPLEMENTATION_HEAD=76cb3362f73325600bed5c8f05ddc80a2aa85fb3
EXACT_HEAD_CI=PASS
EXACT_HEAD_CHECKS=13 successful, 0 failing
CORE_FOCUSED_TESTS=83 passed, 13 subtests passed
AFFECTED_TESTS=438 passed, 43 subtests passed
COMPILEALL=PASS
DIFF_CHECK=PASS
READY=NO
MERGE=NO
ISSUE_CLOSE=NO
PROVIDER_CALL=0
PRODUCTION_MUTATION=0
```

The implementation uses the existing Core image inspection/transform authority, accepts PNG and JPEG input, canonicalizes both to PNG, writes only `BinData/BIN####.png` with `image/png`, and exposes a bounded KAgent `hwpx.insert_image` facade under the existing `CAPABILITY_HWPX_EDIT`. It uses the existing HWPX member reader, serializer splice seam, package validation, text readback, and package-preserving mutation contract. It adds no second HWPX parser, image decoder, archive writer, network, provider, filesystem-write, or Production surface. Direct JPEG embedding remains deferred.

The facade proves output intake, package validation, picture readback, section placement, HWPUNIT receipts, and unrelated member preservation. Exact-head GitHub CI completed successfully at `76cb3362f73325600bed5c8f05ddc80a2aa85fb3`: 13 checks succeeded and none failed. The PR remains Draft and no Ready, merge, issue-close, provider, or Production action was taken.

