# BIO-001 Public-Data Benchmark Scaffold

Issue: `#769`

Status: `RESEARCHING / NARROW`

This directory is an education/research benchmark only. It does not authorize patient-use recommendations, clinical claims, hardware manufacturing, or dataset redistribution.

## Data rule

Third-party subject images are not committed here. Use only a local dataset after its data-specific usage rights are documented. The benchmark requires a provenance/license manifest before producing reportable results.

## Planned comparison

1. deterministic classical image-processing baseline;
2. simple published neural baseline after the data-use gate is closed;
3. a bounded PADIEM candidate only if there is a concrete training/assessment hypothesis to test.

Required metrics include Dice/F1, IoU, precision, recall, latency, and optional nurse-region agreement where the local dataset provides that label.

Implementation self-checks use synthetic images only and are not clinical evidence or independent validation.
