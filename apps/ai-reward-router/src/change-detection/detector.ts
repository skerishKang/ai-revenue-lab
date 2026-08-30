import type { OpportunityVersion } from '../persistence/domain.js';
import type { CandidateOpportunity } from '../extraction/domain.js';
import {
  MATERIAL_TERM_FIELDS,
  NON_MATERIAL_TERM_FIELDS,
  type ChangeSemanticGroup,
  type ComparableTermField,
  type MaterialChangeDetectionResult,
  type NormalizedTermChange,
} from './domain.js';

const LIST_SET_FIELDS = new Set<ComparableTermField>([
  'eligibleCountriesOrRegions',
  'languageRequirements',
  'skillRequirements',
  'deviceOsRequirements',
  'identityKycRequirements',
]);

function semanticGroup(field: ComparableTermField): ChangeSemanticGroup {
  if (field === 'title' || field === 'shortSummary' || field === 'originalLanguage') return 'CONTENT';
  if (field === 'opportunityCategory' || field === 'incomeLadderLevel') return 'CLASSIFICATION';
  if (
    field === 'compensationType' ||
    field === 'advertisedCompensationValue' ||
    field === 'expectedPayoutValue' ||
    field === 'compensationCurrency'
  ) return 'COMPENSATION';
  if (
    field === 'estimatedActiveMinutes' ||
    field === 'estimatedTotalEffortMinutes' ||
    field === 'applicationMinutes' ||
    field === 'qualificationScreeningMinutes' ||
    field === 'preparationMinutes' ||
    field === 'startLatencyMinutes'
  ) return 'EFFORT';
  if (field === 'payoutMethod' || field === 'payoutDelay' || field === 'providerFees') return 'PAYOUT';
  if (field === 'repeatability' || field === 'supplyAvailabilityState') return 'AVAILABILITY';
  if (field === 'canonicalDestinationUrl') return 'DESTINATION';
  return 'ELIGIBILITY';
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === 'object') {
    const source = value as Record<string, unknown>;
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort()) sorted[key] = canonicalize(source[key]);
    return sorted;
  }
  return value;
}

function canonicalStringList(value: unknown): unknown {
  if (value === null) return null;
  if (!Array.isArray(value)) return canonicalize(value);
  return [...value]
    .map((item) => String(item).trim())
    .filter(Boolean)
    .sort();
}

function equivalent(field: ComparableTermField, previousValue: unknown, nextValue: unknown): boolean {
  const previousCanonical = LIST_SET_FIELDS.has(field)
    ? canonicalStringList(previousValue)
    : canonicalize(previousValue);
  const nextCanonical = LIST_SET_FIELDS.has(field)
    ? canonicalStringList(nextValue)
    : canonicalize(nextValue);
  return JSON.stringify(previousCanonical) === JSON.stringify(nextCanonical);
}

function readField(
  record: OpportunityVersion | CandidateOpportunity,
  field: ComparableTermField,
): unknown {
  return (record as unknown as Record<string, unknown>)[field];
}

function buildChange(
  field: ComparableTermField,
  previousValue: unknown,
  nextValue: unknown,
  material: boolean,
): NormalizedTermChange {
  return Object.freeze({
    field,
    group: semanticGroup(field),
    material,
    previousValue,
    nextValue,
  });
}

export function detectMaterialNormalizedTermChanges(
  previousVersion: OpportunityVersion,
  candidate: CandidateOpportunity,
): MaterialChangeDetectionResult {
  const changes: NormalizedTermChange[] = [];

  for (const field of MATERIAL_TERM_FIELDS) {
    const previousValue = readField(previousVersion, field);
    const nextValue = readField(candidate, field);
    if (!equivalent(field, previousValue, nextValue)) {
      changes.push(buildChange(field, previousValue, nextValue, true));
    }
  }

  for (const field of NON_MATERIAL_TERM_FIELDS) {
    const previousValue = readField(previousVersion, field);
    const nextValue = readField(candidate, field);
    if (!equivalent(field, previousValue, nextValue)) {
      changes.push(buildChange(field, previousValue, nextValue, false));
    }
  }

  const materialChanges = Object.freeze(changes.filter((change) => change.material));
  const nonMaterialChanges = Object.freeze(changes.filter((change) => !change.material));
  const disposition = materialChanges.length > 0
    ? 'MATERIAL_CHANGE_REVIEW_REQUIRED'
    : nonMaterialChanges.length > 0
      ? 'NON_MATERIAL_CHANGE'
      : 'NO_CHANGE';

  return Object.freeze({
    previousVersionId: previousVersion.id,
    nextSourceSnapshotId: candidate.sourceSnapshotId,
    changes: Object.freeze(changes),
    materialChanges,
    nonMaterialChanges,
    disposition,
    newVersionRequired: materialChanges.length > 0,
    reviewRequired: materialChanges.length > 0,
    currentVersionReplacementAllowed: false,
  });
}
