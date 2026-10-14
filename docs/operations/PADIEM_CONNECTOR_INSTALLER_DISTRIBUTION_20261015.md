# PADIEM Connector: Windows installer packaging and download distribution (2026-10-15)

> **Public technical release note, not internal business pricing or an authorization to deploy.**
> Single technical tracking issue: [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139).
> Single real Windows release/installation acceptance ledger: [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099).
> Historical release instructions and signing/rollback authority are preserved under those issues and existing policy.
> Product Owner's current direction: the Connector's connection capability should default ON once installed and bound, and the user can switch it OFF from the visible tray.

## Decision and actual status

1. **Use a small, single downloadable PADIEM Connector installer.** The lightweight Connector is a different user experience and artifact from the optional full PADIEM Claw Desktop. Do not silently bundle the full desktop app.
2. **Serve immutable, versioned release binaries from Cloudflare R2 Standard with a custom download domain and cache policy** when the first approved installer exists. The PADIEM website shows a normal download link; it should not stream installer bytes from the application Worker, D1, a website host, or Google Drive.
3. **No artifact exists yet** whose download size has been measured. A suggested *optimization target* is roughly 30 MB, not a measured 30 MB, a size guarantee, or a release blocker. Compare measured byte sizes of candidate builds and choose the smallest package which actually works. Python runtime bundling, GUI/tray code, crypto, WSS, optional OSS helpers and Windows compatibility materially change the size.
4. As of this source inspection, the Windows source/PowerShell \`apps/claw-connect/install.ps1\` in Draft integration [#4572](https://github.com/skerishKang/ai-revenue-lab/pull/4572) requires an existing **Python 3.11+** interpreter; the existing source installer is **not a self-contained customer EXE/MSI**. The reviewed package also has a Node CLI compatibility wrapper, but the PowerShell installer is described as *no-Node*. Do not promise one-click/no-dependency distribution until an actual complete binary package is built and run on a clean PC.
5. Install **once per PC**. Download again only for a manual repair/reinstall or when an update package is needed; the resident starts at Windows sign-in when its canonical device binding exists. Preserve user-requested persistent OFF in tray. No extra account sign-up or per-launch installer download.
6. The main functionality goal remains first authentic **Claw -> Broker -> Windows Resident -> real TXT bytes -> same Claw conversation**, tracked in #4139. Packaging must not delay LOCAL1/LOCAL2 actual integration; build from the accepted single runtime, do not invent a second Broker/Agent.

## Cloudflare storage/traffic math (public vendor facts, not a quote)

**Cloudflare R2 pricing, official as of 2026-10-01:** https://developers.cloudflare.com/r2/pricing/

- **R2 Standard egress to the Internet: free.** This statement does not imply that storage, operations, other Cloudflare services, external providers, or future service plans cost nothing.
- Standard free monthly allowance: **10 GB-month storage, 1 million Class A operations, 10 million Class B read operations**; excess requests and storage are billable. Standard currently costs $0.015/GB-month, $4.50/million Class A and $0.36/million Class B, with Cloudflare billing-unit rounding. Check the current pricing before release.
- **Do not select R2 Infrequent Access just to lower storage cost** for a frequently downloaded public release: it has no Standard free tier and has retrieval charges even though egress is free.
- For one illustrative **50 MB** artifact and one request per initial install, 100 downloads ~= 5 GB egress, 1,000 ~= 50 GB, 10,000 ~= 500 GB. In R2 Standard the **egress part** still costs $0. These examples are a scenario, not the PADIEM binary size or a prediction of install volume. Clients may retry or issue HEAD/range requests; actual Class B operations can exceed a single request per download.
- Use a **custom download domain** connected to R2 rather than production use of \`r2.dev\` (the latter is a development endpoint with rate limits). Example only: \`downloads.padiem.net\` is **not claimed to exist**. https://developers.cloudflare.com/r2/buckets/public-buckets/
- CDN caching is enabled/configured through the R2 custom domain and Cache Rules where needed; **do not assume \`.exe\`/\`.msi\` are cached by default**. https://developers.cloudflare.com/cache/interaction-cloudflare-products/r2/
- A public R2 download bucket should contain only distributable, signed/verified **release artifacts and public checksums/metadata**. Never publish device credentials, logs, private Governance, customer files, or source secrets in it.

## Build / publish / rollback procedure (when the binary exists)

1. LOCAL2/CENTRAL choose a packaging implementation that uses the **existing Connector + canonical Agent/Resident** and optionally vetted open-source *source code* to reduce duplication; no independent MCP service or extra end-user login is imposed. Verify necessary MIT/Apache/license notices for copied dependencies.
2. Build a standalone Windows installable on a clean Windows machine **without preinstalled Python, Node or Git**. Verify actual unsigned and signed artifact sizes, installed disk use, idle RAM, first-launch time and required bundled libraries. A single-file executable may be slower or larger than a compressed setup package: measure instead of guessing.
3. Reuse [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) for signing, immutable artifact SHA-256, provenance, installed-version identity, Windows restart/autostart, uninstall and rollback. Check native WSS connection/DPAPI restore, offline behavior and durable user OFF; do not infer this from an icon alone.
4. Publish **immutable version-named** objects (illustrative \`padiem-connector-<version>-windows-<arch>.exe\`) with their public SHA-256 and size metadata. Record exact Git HEAD, build workflow, artifact checksum, object key and deployed file URL. Never repack silently under the same version name.
5. Link the versioned object from the existing website/Claw connection page. Verify a full download via the custom R2 domain, checksum against the signed artifact, clean-PC installation and **one actual same-conversation Claw TXT** test. Website CTA should not point to a nonexistent file.
6. On rollback, switch the public link back to a previously verified immutable object and (when appropriate) roll back the installed Connector through the existing update flow. Record the observed served version and checksum. Rollback of a file download is not rollback of a running Worker/Broker.
7. Estimate recurring billing from R2 storage and Class A/B requests plus separately metered Worker execution, Cloudflare services, model/Broker traffic and engineering/support costs. These internal business numbers and contracts belong in the **local, non-public Governance** materials referenced from root \`AGENTS.md\`, not public GitHub.

## Cross-document consolidation and scope

| Authority | Sole responsibility | This document adds |
| --- | --- | --- |
| [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139) | Existing Connector + canonical Broker + Claw first real TXT implementation | Distribution approach, current package gap and download-link contract only |
| [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) | Actual Windows installer, signing, pairing, reboots, upgrades and rollback acceptance | Exact artifact-size/checksum and R2 served-download evidence checklist |
| [#2996](https://github.com/skerishKang/ai-revenue-lab/issues/2996) | Long-term OSS adoption/radar | No duplicate OSS approval board; implement reused source under #4139 |
| [#1878](https://github.com/skerishKang/ai-revenue-lab/issues/1878) | Commercial Claw product/pricing analysis | R2 public vendor facts **not** a customer pricing commitment; private enterprise financial terms stay outside GitHub |
| [PADIEM Portfolio Index](PADIEM_PORTFOLIO_ISSUE_DOC_RECONCILIATION_20261013.md) | Which open/closed issue owns each deliverable | Keeps this release note discoverable without a new tracking issue |

## Evidence discipline

\`\`\`text
R2_STANDARD_EGRESS_PRICING=OFFICIAL_VENDOR_VERIFIED
R2_PUBLIC_CUSTOM_DOMAIN=RECOMMENDED_NOT_CONFIGURED
STANDALONE_CONNECTOR_INSTALLER=NOT_BUILT
INSTALLER_DOWNLOAD_SIZE=NOT_MEASURED
CONNECTOR_SIZE_30MB=OPTIMIZATION_TARGET_ONLY
R2_RELEASE_ARTIFACT=NOT_UPLOADED
PRODUCTION_DOWNLOAD_LINK=NOT_LIVE
WINDOWS_CLEAN_INSTALL=NOT_PROVEN
PADIEM_CLAW_REAL_PC_TXT=NOT_PROVEN
\`\`\`
