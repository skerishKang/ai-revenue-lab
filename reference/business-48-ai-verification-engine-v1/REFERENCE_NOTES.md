# Reference notes

Research date: 2026-07-29

## Comparable verification and evidence systems

1. **NIST CSRC — Independent Verification & Validation glossary**  
   https://csrc.nist.gov/glossary/term/independent_verification_and_validation
2. **NISTIR 8397 — Guidelines on Minimum Standards for Developer Verification of Software**  
   https://csrc.nist.gov/pubs/ir/8397/final
3. **SLSA v1.2 — Verifying Artifacts**  
   https://slsa.dev/spec/v1.2/verifying-artifacts
4. **W3C WAI — Template for Accessibility Evaluation Reports**  
   https://www.w3.org/WAI/test-evaluate/report-template/
5. **GitHub Docs — About and troubleshooting status checks**  
   https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks

### Adopted from comparable systems

- NIST: independent verification is a different authority from implementation work and worker self-check;
- NISTIR 8397: developer verification is useful evidence but is not silently promoted to independent validation;
- SLSA: evidence is accepted only when its subject and exact artifact identity match;
- W3C reporting: evaluation scope, method, result, exceptions and unresolved conditions remain explicit;
- GitHub status checks: individual outcomes stay inspectable instead of collapsing into one decorative score.

### Rejected from comparable systems

- proprietary provider chrome, logos, status icons or report screenshots;
- CI-oriented control-tower layouts and repository workflow controls;
- a single aggregate pass percentage;
- treating skipped, neutral or unavailable results as passed;
- stale evidence inheritance across artifact versions;
- automated verdicts presented as human approval.

## Editorial and award-level visual references

1. **NASA Graphics Standards Manual** — NASA archive  
   https://www.nasa.gov/image-article/nasa-graphics-standards-manual/
2. **Anatomy of an AI System** — Kate Crawford and Vladan Joler  
   https://anatomyof.ai/
3. **The Pudding** — visual-essay publication  
   https://pudding.cool/about/
4. **Information is Beautiful Awards 2019 winners** — award archive  
   https://www.informationisbeautifulawards.com/news/485-information-is-beautiful-awards-2019-the-winners

### Adopted from editorial references

- NASA manual: disciplined indexing, technical marginal labels, controlled grid and plate-like hierarchy;
- Anatomy of an AI System: evidence-dense annotation and visible relationships without reducing complexity to a dashboard score;
- The Pudding: a clear editorial reading order that lets explanation and visual evidence support one another;
- Information is Beautiful winners: strong information hierarchy, restrained emphasis and legibility under high information density.

### Rejected from editorial references

- NASA identity marks, typography prescriptions and brand assets;
- the large systems-map composition or illustrative language of Anatomy of an AI System;
- scroll-driven narrative mechanics from visual essays, because Phase 1 permits only minimal review interaction;
- chart, map or infographic forms that would imply measured production data;
- any copied layout, illustration, icon, certification mark or proprietary interface.

## Product distinction

### Difference from Business 42

Business 42 coordinates an entire development authority chain. Business 48 is the narrower reusable verification component: one submitted artifact, one exact version, bounded checks, evidence, exceptions, validator verdict and separate approval. It therefore avoids control-room maps, role orchestration lanes and phase-gate consoles.

### Difference from Business 43

Business 43 visualizes requirement-to-software-delivery production. Business 48 does not show files moving through a factory, code patches, build pipelines or delivery crates. The visual language is an inspection bench with calibration plates, evidence envelopes and approval-scope records.

### Distinction fixed for Business 48

The adopted result is an **Independent Verification Bench**: one exact artifact is physically and semantically inspected through plates, tags, envelopes, exception records and a separate human-approval seal. The system deliberately avoids a generic green-check dashboard, development control tower, software factory, compliance certificate and SaaS card wall.
