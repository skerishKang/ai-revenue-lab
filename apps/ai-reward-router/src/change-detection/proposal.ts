import type {
  OpportunityChange,
  OpportunityVersion,
  ReviewQueueItem,
} from '../persistence/domain.js';
import { detectMaterialNormalizedTermChanges } from './detector.js';
import type { NextVersionProposal, NextVersionProposalInput } from './domain.js';

function assertProposalInput(input: NextVersionProposalInput): void {
  if (input.provenance.status !== 'SUCCESS') {
    throw new Error('W6 requires a W5 extraction run with SUCCESS status');
  }
  if (input.w5Review.structuralErrors.length > 0) {
    throw new Error('W6 cannot propose a version from a structurally invalid W5 candidate');
  }
  if (input.w5Review.candidateId !== input.candidate.candidateId) {
    throw new Error('W5 review candidateId does not match the candidate');
  }
  if (input.provenance.sourceSnapshotId !== input.candidate.sourceSnapshotId) {
    throw new Error('W5 provenance sourceSnapshotId does not match the candidate');
  }
  if (input.candidate.sourceSnapshotId.trim().length === 0) {
    throw new Error('candidate sourceSnapshotId is required');
  }
}

function buildOpportunityVersion(input: NextVersionProposalInput): OpportunityVersion {
  const candidate = input.candidate;
  const previous = input.previousVersion;
  return Object.freeze({
    id: input.nextVersionId,
    offerId: previous.offerId,
    versionNumber: previous.versionNumber + 1,
    sourceSnapshotId: candidate.sourceSnapshotId,
    title: candidate.title,
    shortSummary: candidate.shortSummary,
    originalLanguage: candidate.originalLanguage,
    verificationState: 'REVIEW_REQUIRED',
    sourceSnapshotHash: input.provenance.inputSnapshotSha256,
    modelId: input.provenance.modelId,
    promptVersion: input.provenance.promptVersion,
    inputHash: input.provenance.inputSnapshotSha256,
    opportunityCategory: candidate.opportunityCategory,
    incomeLadderLevel: candidate.incomeLadderLevel,
    compensationType: candidate.compensationType,
    advertisedCompensationValue: candidate.advertisedCompensationValue,
    expectedPayoutValue: candidate.expectedPayoutValue,
    compensationCurrency: candidate.compensationCurrency,
    estimatedActiveMinutes: candidate.estimatedActiveMinutes,
    estimatedTotalEffortMinutes: candidate.estimatedTotalEffortMinutes,
    applicationMinutes: candidate.applicationMinutes,
    qualificationScreeningMinutes: candidate.qualificationScreeningMinutes,
    preparationMinutes: candidate.preparationMinutes,
    startLatencyMinutes: candidate.startLatencyMinutes,
    payoutMethod: candidate.payoutMethod,
    payoutDelay: candidate.payoutDelay,
    providerFees: candidate.providerFees,
    repeatability: candidate.repeatability,
    supplyAvailabilityState: candidate.supplyAvailabilityState,
    supplyObservedAt: candidate.supplyObservedAt,
    applicationRequired: candidate.applicationRequired,
    qualificationRequired: candidate.qualificationRequired,
    qualificationProbability: candidate.qualificationProbability,
    acceptanceProbability: candidate.acceptanceProbability,
    rejectionOrReversalRisk: null,
    payoutReliability: null,
    eligibleCountriesOrRegions: candidate.eligibleCountriesOrRegions,
    languageRequirements: candidate.languageRequirements,
    skillRequirements: candidate.skillRequirements,
    deviceOsRequirements: candidate.deviceOsRequirements,
    identityKycRequirements: candidate.identityKycRequirements,
    ageRequirements: candidate.ageRequirements,
    taxContractorRequirements: candidate.taxContractorRequirements,
    schedulingRequirements: candidate.schedulingRequirements,
    canonicalDestinationUrl: candidate.canonicalDestinationUrl,
    createdAt: input.createdAt,
  });
}

function buildChangeRecord(
  input: NextVersionProposalInput,
  proposedVersion: OpportunityVersion,
  materialFields: readonly string[],
  groups: readonly string[],
): OpportunityChange {
  return Object.freeze({
    id: input.changeId,
    offerId: input.previousVersion.offerId,
    previousVersionId: input.previousVersion.id,
    newVersionId: proposedVersion.id,
    material: true,
    changeType: `NORMALIZED_TERMS:${groups.join('+')}`,
    summary: `Material normalized terms changed: ${materialFields.join(', ')}`,
    detectedAt: input.detectedAt,
  });
}

function buildReviewQueueItem(
  input: NextVersionProposalInput,
  proposedVersion: OpportunityVersion,
  groups: readonly string[],
): ReviewQueueItem {
  const reasonCodes = new Set<string>(['MATERIAL_TERM_CHANGE']);
  for (const group of groups) reasonCodes.add(`MATERIAL_${group}`);
  for (const riskCode of input.w5Review.riskCodes) {
    if (riskCode !== 'NONE') reasonCodes.add(`W5_${riskCode}`);
  }

  return Object.freeze({
    id: input.reviewQueueId,
    offerVersionId: proposedVersion.id,
    reasonCodes: Object.freeze([...reasonCodes]),
    priority: 'NORMAL',
    state: 'OPEN',
    assignedTo: null,
    createdAt: input.createdAt,
    resolvedAt: null,
  });
}

export function proposeNextOpportunityVersion(input: NextVersionProposalInput): NextVersionProposal {
  assertProposalInput(input);
  const detection = detectMaterialNormalizedTermChanges(input.previousVersion, input.candidate);
  if (!detection.newVersionRequired) {
    return Object.freeze({
      detection,
      proposedVersion: null,
      change: null,
      reviewQueueItem: null,
      currentVersionReplacementAllowed: false,
    });
  }

  const proposedVersion = buildOpportunityVersion(input);
  const materialFields = detection.materialChanges.map((change) => change.field);
  const groups = [...new Set(detection.materialChanges.map((change) => change.group))];
  const change = buildChangeRecord(input, proposedVersion, materialFields, groups);
  const reviewQueueItem = buildReviewQueueItem(input, proposedVersion, groups);

  return Object.freeze({
    detection,
    proposedVersion,
    change,
    reviewQueueItem,
    currentVersionReplacementAllowed: false,
  });
}
