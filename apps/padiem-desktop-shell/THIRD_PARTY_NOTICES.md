# Third-Party Notices — @ai-revenue-lab/padiem-desktop-shell

This package contains third-party material requiring attribution.

## ZCode — zai-org/ZCode (Apache License 2.0)

This package contains portions derived from the ZCode project:

```text
UPSTREAM_REPO=zai-org/ZCode
UPSTREAM_SHA=29628c9acdb81b703bbd4080c207a0e7ce5e276e
UPSTREAM_PATH=packages/shared/src/workspaceFileSearch.ts
ADAPTATION_TYPE=DERIVED
UPSTREAM_LICENSE=Apache-2.0
LOCAL_LICENSE_COPY=./LICENSE.zcode
```

Derived file in this package:
`src/workspace/workspace-file-search.ts` (fuzzy scoring/ranking primitive,
adapted to Padiem contract types; the relative-path-only keyword bonus
replaces the upstream absolute-path leg because the renderer never receives
absolute paths).

**License copy (Apache-2.0 §4(a) distribution requirement):** the complete
text of the Apache License, Version 2.0 under which ZCode is distributed is
included in this package as the byte-exact local copy
[`LICENSE.zcode`](./LICENSE.zcode) (identical to the upstream `LICENSE` file
at the audited revision above). A URL alone does not satisfy §4(a); that
local file is the operative license copy for the ZCode-derived portion.

**Upstream copyright notice (from the upstream LICENSE APPENDIX):**

```text
Copyright 2026 Z.AI Co., Ltd

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

Upstream repository: https://github.com/zai-org/ZCode

## Packaging inclusion contract

When this package is distributed (including future Electron packaging), the
notice and license material MUST be included verbatim:

```text
THIRD_PARTY_NOTICES.md   -> this file
LICENSE.zcode            -> byte-exact Apache-2.0 copy incl. Z.AI notice
```

`electron-builder.yml` declares `THIRD_PARTY_NOTICES.md` and
`LICENSE.zcode` in its `files:` allowlist, so any NSIS/asar build of this
package ships both files. `tests/zcode-provenance-3583.test.ts` pins this
contract deterministically (files exist, byte-hash of `LICENSE.zcode`,
builder allowlist entries, and the provenance header of the derived module).

All other code in this package is original to the Padiem project and carries
no third-party runtime dependencies introduced by the #3583 slice.
