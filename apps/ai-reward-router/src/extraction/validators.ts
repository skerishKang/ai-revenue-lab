import {
  COMPENSATION_TYPES,
  INCOME_LADDER_LEVELS,
  OPPORTUNITY_CATEGORIES,
} from '../persistence/domain.js';
import type {
  CandidateOpportunity,
  ConflictRiskCode,
  EvidenceBinding,
} from './domain.js';

const nonNegativeFields = [
  'advertisedCompensationValue',
  'expectedPayoutValue',
  'estimatedActiveMinutes',
  'estimatedTotalEffortMinutes',
  'applicationMinutes',
  'qualificationScreeningMinutes',
  'preparationMinutes',
  'startLatencyMinutes',
] as const;
const probabilityFields = ['qualificationProbability', 'acceptanceProbability'] as const;

const materialFields = [
  'title',
  'opportunityCategory',
  'incomeLadderLevel',
  'compensationType',
  'advertisedCompensationValue',
  'expectedPayoutValue',
  'compensationCurrency',
  'estimatedActiveMinutes',
  'estimatedTotalEffortMinutes',
  'applicationMinutes',
  'qualificationScreeningMinutes',
  'preparationMinutes',
  'startLatencyMinutes',
  'payoutMethod',
  'payoutDelay',
  'providerFees',
  'repeatability',
  'supplyAvailabilityState',
  'applicationRequired',
  'qualificationRequired',
  'qualificationProbability',
  'acceptanceProbability',
  'eligibleCountriesOrRegions',
  'languageRequirements',
  'skillRequirements',
  'deviceOsRequirements',
  'identityKycRequirements',
  'ageRequirements',
  'taxContractorRequirements',
  'schedulingRequirements',
  'canonicalDestinationUrl',
] as const;

function valueAt(candidate: CandidateOpportunity, field: string): unknown {
  return (candidate as unknown as Record<string, unknown>)[field];
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

export function normalizeCandidate(candidate: CandidateOpportunity): CandidateOpportunity {
  const normalizeList = (value: readonly string[] | null): readonly string[] | null =>
    value === null ? null : Object.freeze([...new Set(value.map((item) => item.trim()).filter(Boolean))].sort());

  return Object.freeze({
    ...candidate,
    title: candidate.title.trim(),
    shortSummary: candidate.shortSummary?.trim() || null,
    originalLanguage: candidate.originalLanguage?.trim().toLowerCase() || null,
    compensationCurrency: candidate.compensationCurrency?.trim().toUpperCase() || null,
    eligibleCountriesOrRegions: normalizeList(candidate.eligibleCountriesOrRegions),
    languageRequirements: normalizeList(candidate.languageRequirements),
    skillRequirements: normalizeList(candidate.skillRequirements),
    deviceOsRequirements: normalizeList(candidate.deviceOsRequirements),
    identityKycRequirements: normalizeList(candidate.identityKycRequirements),
  });
}

export function validateCandidateStructure(candidate: CandidateOpportunity): readonly string[] {
  const errors: string[] = [];
  if (!candidate.candidateId.trim()) errors.push('candidateId is required');
  if (!candidate.sourceSnapshotId.trim()) errors.push('sourceSnapshotId is required');
  if (!candidate.sourceId.trim()) errors.push('sourceId is required');
  if (!candidate.title.trim()) errors.push('title is required');
  if (!OPPORTUNITY_CATEGORIES.includes(candidate.opportunityCategory)) errors.push('opportunityCategory is invalid');
  if (!INCOME_LADDER_LEVELS.includes(candidate.incomeLadderLevel)) errors.push('incomeLadderLevel is invalid');
  if (!COMPENSATION_TYPES.includes(candidate.compensationType)) errors.push('compensationType is invalid');

  for (const field of nonNegativeFields) {
    const value = candidate[field];
    if (value !== null && (!Number.isFinite(value) || value < 0)) errors.push(`${field} must be finite and >= 0 when present`);
  }
  for (const field of probabilityFields) {
    const value = candidate[field];
    if (value !== null && (!Number.isFinite(value) || value < 0 || value > 1)) errors.push(`${field} must be between 0 and 1 when present`);
  }
  if (candidate.compensationCurrency !== null && !/^[A-Z]{3}$/.test(candidate.compensationCurrency)) {
    errors.push('compensationCurrency must be a 3-letter uppercase code when present');
  }
  if (candidate.canonicalDestinationUrl !== null && !isHttpUrl(candidate.canonicalDestinationUrl)) {
    errors.push('canonicalDestinationUrl must be http(s) when present');
  }
  return Object.freeze(errors);
}

export function validateCandidateSemantics(candidate: CandidateOpportunity): readonly string[] {
  const errors: string[] = [];
  if (candidate.compensationType === 'DRAW' && candidate.expectedPayoutValue !== null) {
    errors.push('draw/prize compensation cannot be normalized as guaranteed expected payout');
  }
  if (candidate.qualificationRequired === true && candidate.immediateTodayRouteClaim === true) {
    errors.push('qualification-dependent work cannot claim immediate TODAY_ROUTE completion');
  }
  if (candidate.expectedPayoutValue !== null && candidate.compensationCurrency === null) {
    errors.push('expected payout requires explicit compensation currency');
  }
  if (candidate.advertisedCompensationValue !== null && candidate.compensationCurrency === null) {
    errors.push('advertised compensation requires explicit compensation currency');
  }
  if (candidate.sourceFreshness === 'BROKEN' || candidate.sourceFreshness === 'STALE') {
    errors.push('stale/broken source evidence blocks publication');
  }
  return Object.freeze(errors);
}

export function validateEvidenceCoverage(
  candidate: CandidateOpportunity,
  evidence: readonly EvidenceBinding[],
): readonly string[] {
  const errors: string[] = [];
  for (const binding of evidence) {
    if (binding.sourceSnapshotId !== candidate.sourceSnapshotId) {
      errors.push(`evidence ${binding.candidateField} points to a different source snapshot`);
    }
    if (binding.confidence !== null && (binding.confidence < 0 || binding.confidence > 1)) {
      errors.push(`evidence ${binding.candidateField} confidence must be between 0 and 1`);
    }
  }

  for (const field of materialFields) {
    const value = valueAt(candidate, field);
    if (value === null || value === undefined) continue;
    const hasBinding = evidence.some((item) => item.candidateField === field && item.sourceSnapshotId === candidate.sourceSnapshotId);
    if (!hasBinding) errors.push(`material field ${field} has no source evidence`);
  }
  return Object.freeze(errors);
}

export function classifyConflictRisks(
  candidate: CandidateOpportunity,
  evidence: readonly EvidenceBinding[],
  structuralErrors: readonly string[],
  semanticErrors: readonly string[],
  evidenceErrors: readonly string[],
): readonly ConflictRiskCode[] {
  const risks = new Set<ConflictRiskCode>();
  if (structuralErrors.length > 0) risks.add('MODEL_SCHEMA_FAILURE');
  if (evidenceErrors.length > 0) risks.add('MISSING_CRITICAL_EVIDENCE');
  if (evidence.some((item) => item.conflict)) risks.add('SOURCE_CONFLICT');
  if (candidate.sourceFreshness === 'STALE' || candidate.sourceFreshness === 'BROKEN') risks.add('STALE_OR_BROKEN_SOURCE');
  if (candidate.compensationType === 'VARIABLE' || candidate.compensationType === 'DRAW') {
    if (candidate.expectedPayoutValue !== null || evidence.some((item) => item.candidateField.includes('Compensation') && item.conflict)) {
      risks.add('AMBIGUOUS_COMPENSATION');
    }
  }
  if (candidate.eligibleCountriesOrRegions === null && candidate.qualificationRequired === true) risks.add('AMBIGUOUS_ELIGIBILITY');
  if (candidate.startLatencyMinutes === null && candidate.immediateTodayRouteClaim === true) risks.add('AMBIGUOUS_TIMING');
  if (semanticErrors.length > 0 && risks.size === 0) risks.add('HIGH_RISK_HUMAN_REVIEW');
  if (risks.size === 0) risks.add('NONE');
  return Object.freeze([...risks]);
}
