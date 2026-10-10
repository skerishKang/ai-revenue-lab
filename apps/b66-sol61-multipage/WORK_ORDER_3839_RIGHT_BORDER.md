# LOCAL1 right-frame correction / v2 integration preparation

Repository: skerishKang/ai-revenue-lab
Issue: #3839; update existing Draft #4001 only.
Base PR head: f25b02541726e06bef8685d366e71815394b7614
Latest main observed: 7e00e01146e271f5225d82db0f6f3a0a2c771bf9
Read-only Sol v2: #4010 / a163f11d2e9c734d66c95293464541d85335ebad

Disposition: REPAIR existing Sol-native composition. Source right frame is four
connected rules at x=572.572, y=270.424..605.218, width=0.72pt; body-art filters
discard its final segment. Treat the original outer frame as structural page
furniture, and let generated rows own their grid without overlapping source
rules. Budget last rows against the real subtotal-cell boundary (518.313pt),
not its text baseline (532.6978pt).

Allowed: apps/b66-sol61-multipage/**, local evidence under the current workspace;
.github/workflows/b66-public-standard-template-contract.yml for this renderer's
focused immutable-bundle/font-independent geometry CI only.
Forbidden: published Sol bundle/certificate/PUBLIC_RELEASE_MANIFEST.json;
#4010 branch/files; QuoteCore arithmetic; B14/model #3906; Drive #3871;
Production, Ready conversion, merge, release certification and issue closure.

Acceptance: actual PDFs at 1,2,3,4,8,10,25,100,101,125,500; all-page vector and
72/144dpi boundary checks, first/middle/last images, source-before negative
control and removed-edge mutation, no unintentional generated frame/grid
overlap, row/footer/summary clearance, item order/count, QuoteCore parity,
determinism, certified-v1 1..3 exact-byte preservation, immutable 18 artifacts
and manifest. Read-only v2 combined previews remain PENDING at every item count.
Record exact-head GitHub CI separately from local PDF evidence. Existing source
header double/dotted rules retain their original intentional paint structure;
Owner taste and formal v2 certification remain reserved to CENTRAL/Owner.
