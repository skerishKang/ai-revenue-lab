# Reference notes

Research date: 2026-07-29

## 1. W3C DCAT 3

- Source: https://www.w3.org/TR/vocab-dcat-3/
- Adopted: separate abstract dataset, distribution, data service and catalog record; preserve publisher, licence, issued/modified dates and access method as distinct metadata.
- Rejected: claiming DCAT conformance or rendering an RDF/linked-data administration interface.
- Decision: catalog, source dossier and access-method stations are separate. Readiness does not imply a live service connection.

## 2. W3C PROV-O / PROV model

- Sources: https://www.w3.org/TR/prov-o/ and https://www.w3.org/TR/prov-primer/
- Adopted: make derivation from source entity through transformation activity to normalized field visible.
- Rejected: cryptographic provenance or a formal provenance compliance claim.
- Decision: use field-lineage rails and retain raw values beside transformed values.

## 3. GOV.UK Government Data Quality Framework

- Sources:
  - https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework
  - https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework-guidance
- Adopted: completeness, timeliness, validity and accuracy are different; communicate missing records and intended-use trade-offs.
- Rejected: a single quality score or green dashboard.
- Decision: current, stale and unknown are explicit; coverage incomplete and known limitation remain after completion.

## 4. W3C Data Quality Vocabulary

- Source: https://www.w3.org/TR/vocab-dqv/
- Adopted: quality annotations help users judge fitness for purpose rather than proving universal quality.
- Rejected: certification or objective completeness guarantees.
- Decision: quality checks are contextual annotations, not approval.

## 5. Open data licensing and endorsement boundaries

- Sources:
  - https://creativecommons.org/licenses/by/4.0/
  - https://opendefinition.org/licenses-md/conformant/OGL-UK-2.0/
- Adopted: licence statements, attribution and non-endorsement should remain explicit; summaries are not legal advice.
- Rejected: legal clearance, warranty or official endorsement claims.
- Decision: every licence surface says `LICENCE STATEMENT — NOT LEGAL ADVICE`; the package retains `NO OFFICIAL ENDORSEMENT`.

## Final visual decisions

- Precision workshop rather than API marketplace, portal clone or cloud dashboard.
- Warm source documents, deep teal workshop surfaces, process orange, inspection red and brass freshness stamps.
- Three focal assets communicate source authority, mapping lineage and stale/limitation states.
- Access method is documentation only; no active endpoint state or connection animation appears.

## Product distinction

- Business 30 explains procedures; Business 49 specifies reusable public-data connections.
- Business 31 preserves citizen/staff experience; Business 49 preserves dataset metadata, mapping and quality boundaries.
- Business 50 owns private enterprise connectors; Business 49 uses only fictional public-source fixtures.
