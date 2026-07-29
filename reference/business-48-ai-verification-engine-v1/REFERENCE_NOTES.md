# Reference notes

Research date: 2026-07-29

## Primary references reviewed

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

## Adopted patterns

- objective-third-party review is visually separated from worker self-check;
- verification evidence is bound to the exact artifact version;
- the evidence record preserves method, result, exception and scope;
- automated checks and manual review are shown as different sources;
- passed, failed, skipped and unavailable are explicit words, not colors alone;
- failed history remains visible after correction and retest;
- unavailable evidence is recorded as an unresolved condition, not negative evidence;
- validator verdict and human approval are separate authorities;
- approval is bounded to listed criteria and one exact artifact version.

## Rejected patterns

- generic green-check dashboard;
- one aggregate quality score;
- treating skipped or neutral infrastructure states as product-level pass;
- stale evidence inheritance;
- compliance-certificate styling or universal certification language;
- worker self-approval;
- implied repository mutation, merge or deployment;
- real CI provider UI, logos, proprietary reports or source screenshots.

## Difference from Business 42

Business 42 coordinates an entire development authority chain. Business 48 is the narrower reusable verification component: one submitted artifact, one exact version, bounded checks, evidence, exceptions, validator verdict and separate approval. It therefore avoids control-room maps, role orchestration lanes and phase-gate consoles.

## Difference from Business 43

Business 43 visualizes requirement-to-software-delivery production. Business 48 does not show files moving through a factory, code patches, build pipelines or delivery crates. The visual language is an inspection bench with calibration plates, evidence envelopes and approval scope records.

## Design references

The composition borrows only general editorial qualities from archival conservation tables, laboratory calibration sheets and legal evidence folios: large specimen plate, typed marginal labels, physical layering and visible annotation. No proprietary interface or official certification mark is copied.
