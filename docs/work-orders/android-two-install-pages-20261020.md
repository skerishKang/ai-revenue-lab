# Android app installation and update — TWO customer-facing pages

STATUS: DRAFT_SCOPE_ONLY / IMPLEMENTED=NO
BASE_MAIN: b438806a65f2dbf74466bb1b222256d3f7706750

## Owner decision (2026-10-20): TWO pages, TWO apps per page

Page A — PADIEM customers
1. PADIEM Chat / Claw (one unified app)
2. PADIEM Connector

Page B — B66 quotation customers
1. B66 Quotation app
2. Connector (**no PADIEM branding in the B66 customer-facing name, label, icon, page, and installer presentation**)

Do NOT implement a single portal with three unrelated buttons. Users enter the corresponding customer-facing page and see exactly its two installers, versions and update links. Exact public domains/URLs are unassigned and require existing deployment authority.

## Reuse and inventory before implementation
- Android WebView sign-in handoff #5162 merged; identify actual Chat/Claw app project/APK/signing path, do not duplicate.
- Android connector Kotlin PR #5179 OPEN; do not modify its active files or merge it from this lane. Coordinate the distribution contract with its owner.
- B66 Android standalone app not yet verified. Reuse current B66 mobile web surface; packaging is a separate implementation slice.
- Confirm whether the B66-branded Connector is technically the same signed APK with different web-page labeling or needs a distinct application ID, app label/icon and signature. Do not silently invent separate identities or cross-app updates.

## Shared release and update capabilities
- Each customer page offers current installers, version/date/checksum, release notes, compatibility, and deterministic download references.
- Maintain a signed release manifest for each app/package; versionCode monotonic, package ID and signing lineage immutable per installed product.
- Reuse existing CI/build/R2 and deployment channels only where authorized; do not modify COM2 runner workflow or connector functionality.
- Built-in Android app update check can download an approved signed APK and hand it to Android's installer. Device policy / installer ownership determines whether unattended installation is possible; do not promise silent install on unmanaged consumer phones.
- Verify downgrade rejection, invalid signatures/checksums, offline/failure recovery, no mixed customer-channel downloads, and existing-user update without data loss.

## LOCAL delivery sequence
1. Inventory all existing app projects, signed APK/AAB artifacts, keystore custody and real package IDs.
2. Create two distinct mobile-friendly customer-facing install pages with two exact app cards on each page.
3. Wire versioned release metadata and an update mechanism without forking existing Connector feature code.
4. Build/test only where actual signing and artifacts are available; differentiate static pages, debug APK, release-signed APK, real device install/update and Play distribution.
5. Implement via a LOCAL PR with focused tests and required CI. Do not claim deploy/live verified without evidence.

## Excluded
No new Connector file-read, pairing, broker, Mesh, Android device activation or server authority; no secrets in GitHub; no business/customer policy changes.

This draft documents the owner-approved page topology and is **not** a functional implementation.
