import type { SourceCollectionGate } from '../source-policy/domain.js';
import { OUTLIER_PRE_CURATION_GATES } from './outlier.js';
import {
  OUTLIER_VERIFIED20_RECORD_V2,
  OUTLIER_W8_V2_REVIEW,
} from './outlier-material-change.js';
import type { Verified20Record } from './domain.js';

/** Final acquisition/evidence/review gates for the currently observed Outlier v2. */
export const OUTLIER_FINAL_GATES_V2: readonly SourceCollectionGate[] = Object.freeze(
  OUTLIER_PRE_CURATION_GATES.map((item, index) => {
    if (index === 5) {
      return Object.freeze({
        ...item,
        status: 'PASS' as const,
        evidence: 'W8_OUTLIER_V2_FIELD_LEVEL_EVIDENCE',
        notes: 'Fresh v2 record binds the current Korean Voice AI Evaluator role, compensation ceiling, location, onboarding, task modality and schedule claims to official public evidence.',
      });
    }
    if (index === 6) {
      return Object.freeze({
        ...item,
        status: 'PASS' as const,
        evidence: 'change-w8-outlier-ko-v1-v2',
        notes: 'W6-style immutable material-change handling retained v1, created v2 and linked the role/task-modality change.',
      });
    }
    if (index === 7) {
      return Object.freeze({
        ...item,
        status: 'PASS' as const,
        evidence: OUTLIER_W8_V2_REVIEW.id,
        notes: 'CENTRAL reviewed and approved v2 after the material role/task-modality change; acceptance probability, guaranteed hours and future supply remain UNKNOWN.',
      });
    }
    return item;
  }),
);

/** Ledger-facing current record. Historical v1 and raw v2 construction remain immutable/queryable. */
export const OUTLIER_CURRENT_VERIFIED20_RECORD: Verified20Record = Object.freeze({
  ...OUTLIER_VERIFIED20_RECORD_V2,
  sourceGates: OUTLIER_FINAL_GATES_V2,
});
