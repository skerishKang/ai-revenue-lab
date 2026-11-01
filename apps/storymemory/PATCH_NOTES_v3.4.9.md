# StoryMemory v3.4.9

SM-092 Expert / Official Verification + Attestation Program.

- Adds verifier identity, credential, verification-request, attestation audit, expiry/revocation and public verification-state boundaries for Marketplace M7.
- EXPERT/OFFICIAL trust is bound to exact Pack version + Source fingerprint + verification scope + approved request + active verifier + active credential.
- New Pack versions and forks do not inherit verification.
- Popularity, ratings, installs and sales never create VERIFIED status.
- Fixes Universal provenance compatibility so canonical Marketplace tier `expert` can support VERIFIED provenance when valid Source evidence is actually used.
- Production seeds no real verifier, credential, request, or Expert/Official attestation.
- Adds no Source body and no per-Source knowledge precompute.
- Full regression: 27/27 PASS; static corpus byte regression: 192 files changed 0.
- Deployment remains deferred to BI Portal `/b61/`.
