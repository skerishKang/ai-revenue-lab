# Third-Party Notices — @ai-revenue-lab/padiem-desktop-shell

## zai-org/ZCode (Apache License 2.0)

This package contains portions derived from the ZCode project:

```text
UPSTREAM_REPO=zai-org/ZCode
UPSTREAM_SHA=29628c9acdb81b703bbd4080c207a0e7ce5e276e
UPSTREAM_PATH=packages/shared/src/workspaceFileSearch.ts
ADAPTATION_TYPE=DERIVED
```

Derived file in this package:
`src/workspace/workspace-file-search.ts` (fuzzy scoring/ranking primitive,
adapted to Padiem contract types; the relative-path-only keyword bonus
replaces the upstream absolute-path leg because the renderer never receives
absolute paths).

ZCode is licensed under the Apache License, Version 2.0
(https://www.apache.org/licenses/LICENSE-2.0). The upstream repository is
https://github.com/zai-org/ZCode. Required Apache-2.0 attribution is
preserved in the derived file header and in this notice.

All other code in this package is original to the Padiem project and carries
no third-party runtime dependencies introduced by the #3583 slice.
