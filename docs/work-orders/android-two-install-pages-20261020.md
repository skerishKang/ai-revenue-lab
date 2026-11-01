# Android app installation and update — TWO customer-facing pages

STATUS: DRAFT_SCOPE_ONLY / IMPLEMENTED=NO — the two customer pages, their
download links and version metadata DO NOT EXIST yet. Nothing on this page is
live; treat every product below as 준비 중 until its installer is real.
UPDATED: 2026-11-02 progress refresh from salvage of PR #5185 (page topology
unchanged; inventory updated to what main actually holds today).
BASE_MAIN: 732c8c597ff14b3abbbca6f5b8854545e6c38025

## Owner decision (2026-10-20): TWO pages, TWO apps per page

Page A — PADIEM customers
1. PADIEM Chat / Claw (one unified app)
2. PADIEM Connector

Page B — B66 quotation customers
1. B66 Quotation app
2. Connector (**no PADIEM branding in the B66 customer-facing name, label, icon, page, and installer presentation**)

Do NOT implement a single portal with three unrelated buttons. Users enter the corresponding customer-facing page and see exactly its two installers, versions and update links. Exact public domains/URLs are unassigned and require existing deployment authority.

## Reuse and inventory — updated 2026-11-02 (what main actually has)

- Chat/Claw Android app project EXISTS in source: `apps/padiem-chat-claw-native/`
  (#5435, native React Native client for PADIEM Chat and Claw). No signed APK,
  no release manifest, no install page and no updater are built from it yet —
  준비 중. The old instruction to "identify the actual Chat/Claw app project"
  is answered by this path; do not start a second app project.
- Connector Android app project EXISTS in source: `apps/padiem-android-connector/`
  (Kotlin connector, #5080 line — #5179 MERGED as 6e4ac6759, sign-in handoff
  follow-ups #5257/#5337/#5345/#5369 landed). It is a separately owned lane:
  do not modify its active files or merge it from this lane; coordinate the
  distribution contract with its owner.
- B66 Android standalone app: STILL NOT VERIFIED and NOT BUILT — 준비 중.
  Reuse the current B66 mobile web surface until packaging is a real slice.
- Whether the B66-branded Connector is the same signed APK with different
  web-page labeling or a distinct application ID, label/icon and signature is
  STILL UNCONFIRMED. Do not silently invent separate identities or cross-app
  updates.
- Customer-facing install/update pages (both pages A and B): NOT IMPLEMENTED —
  준비 중. No public domain or download URL has been assigned.

## Shared release and update capabilities

- Each customer page offers current installers, version/date/checksum, release notes, compatibility, and deterministic download references.
- Maintain a signed release manifest for each app/package; versionCode monotonic, package ID and signing lineage immutable per installed product.
- Reuse existing CI/build/R2 and deployment channels only where authorized; do not modify COM2 runner workflow or connector functionality.
- Built-in Android app update check can download an approved signed APK and hand it to Android's installer. Device policy / installer ownership determines whether unattended installation is possible; do not promise silent install on unmanaged consumer phones.
- Verify downgrade rejection, invalid signatures/checksums, offline/failure recovery, no mixed customer-channel downloads, and existing-user update without data loss.

## LOCAL delivery sequence

1. Inventory all existing app projects, signed APK/AAB artifacts, keystore custody and real package IDs. (Projects inventoried above; artifacts and keystore custody still unverified.)
2. Create two distinct mobile-friendly customer-facing install pages with two exact app cards on each page.
3. Wire versioned release metadata and an update mechanism without forking existing Connector feature code.
4. Build/test only where actual signing and artifacts are available; differentiate static pages, debug APK, release-signed APK, real device install/update and Play distribution.
5. Implement via a LOCAL PR with focused tests and required CI. Do not claim deploy/live verified without evidence.

## Excluded

No new Connector file-read, pairing, broker, Mesh, Android device activation or server authority; no secrets in GitHub; no business/customer policy changes.

This draft documents the owner-approved page topology and is **not** a functional implementation.
