# Reference Notes

## Product and governance references

1. **NIST SP 800-53 Rev. 5 — CM-3 Configuration Change Control / AC-5 Separation of Duties**
   Source: https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final
   Adopted: explicit proposal, justification, testing, review and disposition of changes; authority lanes that prevent one actor from requesting, implementing, validating and approving the same change.
   Rejected: compliance-control language as the primary product interface.

2. **NIST SP 800-218 — Secure Software Development Framework**
   Source: https://csrc.nist.gov/pubs/sp/800/218/final
   Adopted: evidence-backed development practices, preserved task boundaries and review records across the software lifecycle.
   Rejected: presenting security framework coverage as a product score.

3. **GitHub protected branches and required reviews/status checks**
   Sources: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches and https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks
   Adopted: latest-head review authority, stale approval invalidation, required checks as evidence, and the distinction between mergeability and authorization.
   Rejected: GitHub navigation, pull-request layout, badges, icons and merge box.

4. **SLSA v1.2 — provenance and artifact verification**
   Sources: https://slsa.dev/spec/v1.2/provenance and https://slsa.dev/spec/v1.2/verifying-artifacts
   Adopted: evidence must be tied to the artifact/revision it claims to verify and compared against declared expectations; unverifiable or mismatched evidence remains visible but cannot authorize action.
   Rejected: supply-chain level scoring and automated trust claims in this UI-only reference.

5. **GitLab deployment approvals**
   Source: https://docs.gitlab.com/ci/environments/deployment_approvals/
   Adopted: deployment approval is a separate authority record and does not itself execute deployment; default separation between triggerer and approver.
   Rejected: GitLab environment/deployment screen structure and proprietary UI.

## Editorial and information-design references

- Mission control flight-rule binders: adopt terse authority labels, immutable identifiers, disposition marks and exception retention; reject terminal walls and live telemetry imitation.
- Industrial quality-control travelers: adopt one work order moving through role-separated checkpoints; reject factory-production metaphors that imply autonomous code generation.
- Archival ledger systems: adopt fixed-head records, marginal blocker slips and signed decision memoranda; reject decorative nostalgia and legal-evidence styling.

## Visual direction adopted

- dark graphite mission board with mineral-paper folios;
- rectangular authority lanes rather than rounded SaaS cards;
- immutable exact-head ledger always near evidence and decisions;
- textual gate labels in addition to color and shape;
- stale evidence remains crossed, dated and readable instead of disappearing;
- blockers remain present after completion;
- recommended and authorized actions occupy separate columns;
- human approval seals the control record, not the implementation itself.

## Rejected patterns

- generic project dashboard or card grid;
- GitHub, Jira, Linear or Cloudflare interface copy;
- terminal wall, coding chat, kanban and employee ranking;
- green checkmarks that imply human approval;
- automatic merge, deployment or phase advancement;
- implementation worker self-approval;
- stale evidence silently inheriting current-head authority.

## Portfolio boundaries

- **Business 43 · AI Software Factory** produces a bounded requirement-to-delivery package. Business 42 governs who may act, which exact source is authoritative, what evidence is sufficient and what happens next.
- **Business 44 · Portfolio Operations Console** coordinates many products, priorities and deployments. Business 42 controls one software workstream at exact-head level.
- **Business 48 · AI Verification Engine** is a reusable validation/approval component. Business 42 coordinates the broader product-authority, implementation, independent-validation, gate and human-decision chain around it.

No proprietary interface, branding, screenshot, icon, copy or layout was reproduced.
