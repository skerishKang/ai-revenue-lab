# Reference Notes

## Product framing

**Promise:** turn one authorized enterprise-data connection request into a reviewable, least-privilege access-and-connector specification before any live connection exists.

**Primary user moment:** a data owner and connector operator review a synthetic request for a supplier-renewal evidence packet and need to see what is requested, what is approved, what remains prohibited, how fields map and how access can be revoked.

**Visual metaphor:** a **Private Data Access Review Room** composed of source-system dossiers, permission cut-lines, field mapping sheets, retention bands and revocation records.

## Comparable product research

Research was used for governance concepts only. No interface, brand asset, copy block or screen was copied.

1. **Microsoft Purview Unified Catalog / Data Map**
   - Source: https://learn.microsoft.com/en-us/purview/data-governance-plan
   - Relevant pattern: governance metadata must be distinguished from access to underlying data; owner and role hierarchy matters.
   - Adopted: explicit owner authority, metadata/content distinction and least-privilege framing.
   - Rejected: catalog/search-first information architecture and Microsoft visual language.

2. **Microsoft Purview data product access policies**
   - Source: https://learn.microsoft.com/en-us/purview/unified-catalog-data-product-access-policies
   - Relevant pattern: access requests, policy owners and approvers are distinct, and granting a data-product permission does not automatically perform every underlying access step.
   - Adopted: requested scope is not shown as approved scope; owner decision is separate.
   - Rejected: generic portal workflow and live policy administration.

3. **Immuta purpose-based and restricted data policies**
   - Sources:
     - https://documentation.immuta.com/2026.1/governance/author-policies-for-data-access-control/authoring-policies-in-secure/data-policies/how-to-guides/restricted-data-policies
     - https://documentation.immuta.com/2026.1/governance/author-policies-for-data-access-control/authoring-policies-in-secure/data-policies/reference-guides/limit-to-purpose-policies
   - Relevant pattern: data-owner authority, purpose limitation and granular field/row policy.
   - Adopted: authorized purpose, owner-limited scope and field-level exclusions.
   - Rejected: live enforcement controls, masking configuration and query-time behavior.

4. **Okta Identity Governance access reviews**
   - Sources:
     - https://help.okta.com/en-us/Content/Topics/identity-governance/access-certification/sec-access-review/sar.htm
     - https://help.okta.com/en-us/Content/Topics/identity-governance/em/manage-entitlements.htm
   - Relevant pattern: reviewer authority, temporary/permanent revocation and decision evidence.
   - Adopted: access is structurally revocable and review evidence is explicit.
   - Rejected: identity-centric user surveillance cues, anomaly scoring and admin-console layout.

5. **Google Cloud Knowledge Catalog / Dataplex lineage and metadata**
   - Source: https://cloud.google.com/products/knowledge-catalog
   - Relevant pattern: source identity, technical metadata and governance context are related but distinct.
   - Adopted: source-to-normalized field provenance.
   - Rejected: enterprise search, agent connection and data-estate overview dashboard.

## Editorial and visual references

1. **The National Archives — new online catalogue design**
   - Source: https://www.nationalarchives.gov.uk/blogs/digital/new-online-catalogue-blog/how-the-design-of-our-new-online-catalogue-puts-users-first/
   - Adopted: record information first, hierarchy subordinate to the record, restrained institutional typography.

2. **U.S. National Archives — records-management forms and guidance**
   - Sources:
     - https://www.archives.gov/frc/forms
     - https://www.archives.gov/guidance/records-management-guidance
   - Adopted: paper-form grammar, folio numbers, rule lines, stamps and retention/disposition language.

3. **Pentagram editorial design portfolio**
   - Source: https://www.pentagram.com/editorial-design
   - Adopted: editorial hierarchy, coordinated serif/sans/monospace roles and dense-but-readable information framing.
   - Rejected: magazine-like decorative spectacle that would weaken governance clarity.

4. **Carbon Design System data-table accessibility**
   - Source: https://carbondesignsystem.com/components/data-table/accessibility/
   - Adopted: semantic tables, explicit headers and focus-visible controls.
   - Rejected: Carbon component styling or branded interaction patterns.

## Composition decisions

- Warm archival paper, navy institutional ink and red permission cut-lines replace generic cybersecurity gradients.
- The center of gravity is documentary: dossiers, signed authority blocks, mapping rows and control bands.
- `DATA OWNER`, `REQUESTER` and `CONNECTOR OPERATOR` use separate cards and capabilities.
- Requested, approved and prohibited scope never share the same status color or container.
- Excluded fields are shown as persistent red records, not hidden omissions.
- Retention and revocation occupy full structural modules rather than secondary badges.
- Mobile preserves prohibited paths, credential boundary, retention and revocation above the final readiness status.

## Explicit rejections

- copied Gmail, Google Drive, Slack, database or file-manager screens;
- credential vaults, token-value mocks or password inputs;
- employee activity, productivity, anomaly or risk scoring;
- generic security dashboard card grids;
- enterprise search results or universal data catalogue;
- lock-wall imagery, shield motifs and purple AI gradients;
- any implication that the reference is connected, extracting or training a model.
