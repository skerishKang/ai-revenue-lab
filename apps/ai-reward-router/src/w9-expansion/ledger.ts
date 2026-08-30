import { VERIFIED20_RECORDS } from '../verified20/ledger.js';
import { verified50Progress } from './domain.js';
import { PANELPOWER_CURRENT_W9_RECORDS } from './panelpower-current.js';

export const W9_EXPANSION_RECORDS = Object.freeze([
  ...PANELPOWER_CURRENT_W9_RECORDS,
]);

export const VERIFIED50_PROGRESS = verified50Progress(VERIFIED20_RECORDS, W9_EXPANSION_RECORDS);

export const W9_GATE_STATUS = Object.freeze({
  verifiedCount: VERIFIED50_PROGRESS.verifiedCount,
  targetCount: VERIFIED50_PROGRESS.targetCount,
  remainingCount: VERIFIED50_PROGRESS.remainingCount,
  baseline20Passed: VERIFIED50_PROGRESS.baseline20Passed,
  duplicateExpansionOrdinalDetected: VERIFIED50_PROGRESS.duplicateExpansionOrdinalDetected,
  duplicateOpportunityDetected: VERIFIED50_PROGRESS.duplicateOpportunityDetected,
  gatePassed: VERIFIED50_PROGRESS.gatePassed,
});
