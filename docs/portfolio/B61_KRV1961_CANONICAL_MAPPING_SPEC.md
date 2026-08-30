# B61 — KRV 1961 Canonical Mapping Contract

Status: SPEC_ONLY / NO PRODUCTION MUTATION
Owner decision: Use existing 1961 Korean Revised Version text; do not generate a new Korean Bible translation.

## Coordinate model

B61 MUST preserve the Korean source's raw coordinates:

- source_edition = KRV-1961
- raw_book
- raw_chapter
- raw_verse
- text

B61 MAY additionally assign a canonical cross-source coordinate for joining to the existing WEB corpus:

- canonical_book
- canonical_chapter
- canonical_verse

The raw KRV coordinate and text MUST NOT be rewritten to force a 1:1 match with WEB.

## Current evidence

- Bible Society of Korea identifies `성경전서 개역한글판(1961)` as the 1961 edition; official BSK pages expose the KRV text online.
- `bluesaurel/Korean-Bible-1961-KRV` reports 66 books / 1,189 chapters / 31,102 verses and claims BSK cross-validation. It is third-party and is not yet authoritative.
- `crizin/bible-db` reports KRV 1961 at 31,101 verses, says its KRV was crawled from `holybible.or.kr`, and says a second `bible.bskorea.or.kr` crawl was diffed. It explicitly preserves raw Korean coordinates and adds canonical KJV coordinates to reconcile four verse-boundary differences.

## Required mapping gate

1. Obtain an immutable KRV-1961 source snapshot.
2. Verify source edition identity.
3. Validate 66 books / 1,189 chapters.
4. Compare independent KRV source candidates at representative samples and boundary cases.
5. Enumerate every KRV-vs-WEB verse boundary/numbering difference.
6. Build a deterministic mapping table keyed by source edition + raw coordinates.
7. Prove that every B61 WEB canonical passage either maps to exactly one KRV verse/span or is explicitly classified as a boundary exception.
8. Preserve all raw KRV text byte-for-byte; mapping is metadata only.
9. Record source URL/repository, commit/snapshot, retrieval date, hashes, rights/provenance, and attribution/integrity requirements.
10. Only after this gate passes may B61 Bible static corpus generation begin.

## Non-goals

- No AI translation.
- No Qwen/M2M100 translation.
- No bulk corpus replacement.
- No Cloudflare/Pages mutation.
- No Neon schema mutation.
- No UI redesign.
