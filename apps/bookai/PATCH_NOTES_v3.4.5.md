# StoryMemory v3.4.5 — SM-085 Pack Registry + Marketplace MVP

- Adds `storymemory-pack-registry-1.0` browser runtime for public Pack discovery, Source compatibility, install/attach, detach/uninstall, persistent install provider hooks, and registry attestation handoff.
- Adds a small Pack Marketplace panel to the existing RIGHT AI Companion; Book shelf/page-curl and Source Viewer contracts are preserved.
- Adds one free public Odyssey alias Search Pack artifact with no Source body and no verified attestation.
- Adds Neon metadata-only registry contract: `pack_registry`, `pack_versions`, `pack_attestations`, `pack_installs`.
- Main registry is seeded with one public/free AUTO-GENERATED listing. Payment/settlement is not implemented.
- Publication hard gates reject Source-body inclusion and direct private-published state; creators cannot self-attest or self-publish through authenticated RLS policies.
- LLM-first / Source-grounded / DB-on-demand remains the governing architecture. No entity/relation/answer-card/embedding expansion is part of SM-085.
- Cloudflare / BI Portal / DNS deployment remains deferred to `/b61/`.
