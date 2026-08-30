import type { Verified20Record, VerifiedOpportunityTrustRecord } from '../verified20/domain.js';
import { validateVerified20Record, validateVerifiedOpportunityTrustRecord, verified20Progress } from '../verified20/domain.js';

export interface W9ExpansionRecord extends VerifiedOpportunityTrustRecord {
  readonly ordinal: number;
}

export function validateW9ExpansionRecord(record: W9ExpansionRecord) {
  const core = validateVerifiedOpportunityTrustRecord(record);
  const errors = [...core.errors];
  if (!Number.isInteger(record.ordinal) || record.ordinal < 21 || record.ordinal > 50) {
    errors.unshift('W9 ordinal must be an integer from 21 to 50');
  }
  return Object.freeze({ countable: errors.length === 0, errors: Object.freeze(errors) });
}

export function verified50Progress(
  baseline20: readonly Verified20Record[],
  expansion: readonly W9ExpansionRecord[],
) {
  const baselineProgress = verified20Progress(baseline20);
  const expansionValidations = expansion.map((record) => validateW9ExpansionRecord(record));
  const seenOpportunityIds = new Set<string>();
  const seenOrdinals = new Set<number>();
  let count = 0;

  baseline20.forEach((record) => {
    const validation = validateVerified20Record(record);
    if (!validation.countable) return;
    if (seenOpportunityIds.has(record.opportunity.id)) return;
    seenOpportunityIds.add(record.opportunity.id);
    count += 1;
  });

  expansion.forEach((record, index) => {
    const validation = expansionValidations[index];
    if (!validation?.countable) return;
    if (seenOrdinals.has(record.ordinal) || seenOpportunityIds.has(record.opportunity.id)) return;
    seenOrdinals.add(record.ordinal);
    seenOpportunityIds.add(record.opportunity.id);
    count += 1;
  });

  const duplicateExpansionOrdinalDetected = new Set(expansion.map((record) => record.ordinal)).size !== expansion.length;
  const allIds = [...baseline20.map((record) => record.opportunity.id), ...expansion.map((record) => record.opportunity.id)];
  const duplicateOpportunityDetected = new Set(allIds).size !== allIds.length;
  const expectedOrdinalsPresent = count === 50 && Array.from({ length: 30 }, (_, index) => index + 21).every((ordinal) => seenOrdinals.has(ordinal));
  const gatePassed = baselineProgress.gatePassed && count === 50 && expectedOrdinalsPresent && !duplicateOpportunityDetected;

  return Object.freeze({
    verifiedCount: count,
    targetCount: 50,
    remainingCount: 50 - count,
    baseline20Passed: baselineProgress.gatePassed,
    gatePassed,
    duplicateExpansionOrdinalDetected,
    duplicateOpportunityDetected,
    expansionValidations: Object.freeze(expansionValidations),
  });
}
