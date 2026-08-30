import { createHash } from 'node:crypto';
import type {
  CandidateOpportunity,
  EvidenceBinding,
  ExtractionInput,
  ExtractorKind,
  ExtractorOutput,
  OpportunityExtractor,
} from './domain.js';

export type FakeExtractionScenario =
  | 'FIXED_SURVEY'
  | 'DRAW_MAXIMUM'
  | 'UNKNOWN_COMPENSATION'
  | 'AI_WORK_QUALIFIED'
  | 'CONFLICTING_COMPENSATION'
  | 'STALE_SOURCE'
  | 'MALFORMED_NEGATIVE'
  | 'MISSING_EVIDENCE';

function hash(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function binding(
  snapshotId: string,
  candidateField: string,
  extractedValue: unknown,
  conflict = false,
): EvidenceBinding {
  return Object.freeze({
    candidateField,
    sourceSnapshotId: snapshotId,
    sourceLocator: `fixture://${candidateField}`,
    evidenceTextHash: hash(`${candidateField}:${JSON.stringify(extractedValue)}`),
    evidenceType: 'SOURCE_TEXT',
    extractedValue,
    confidence: 1,
    conflict,
  });
}

function baseCandidate(input: ExtractionInput): CandidateOpportunity {
  return {
    candidateId: `${input.runId}:candidate`,
    sourceSnapshotId: input.snapshot.id,
    sourceId: input.snapshot.sourceId,
    title: 'Synthetic opportunity',
    shortSummary: null,
    originalLanguage: 'en',
    opportunityCategory: 'OTHER_VERIFIED_ONLINE_INCOME',
    incomeLadderLevel: 'TASK_WORK',
    compensationType: 'OTHER',
    advertisedCompensationValue: null,
    expectedPayoutValue: null,
    compensationCurrency: null,
    estimatedActiveMinutes: null,
    estimatedTotalEffortMinutes: null,
    applicationMinutes: null,
    qualificationScreeningMinutes: null,
    preparationMinutes: null,
    startLatencyMinutes: null,
    payoutMethod: null,
    payoutDelay: null,
    providerFees: null,
    repeatability: null,
    supplyAvailabilityState: null,
    supplyObservedAt: null,
    applicationRequired: null,
    qualificationRequired: null,
    qualificationProbability: null,
    acceptanceProbability: null,
    eligibleCountriesOrRegions: null,
    languageRequirements: null,
    skillRequirements: null,
    deviceOsRequirements: null,
    identityKycRequirements: null,
    ageRequirements: null,
    taxContractorRequirements: null,
    schedulingRequirements: null,
    canonicalDestinationUrl: null,
    sourceFreshness: 'CURRENT',
    immediateTodayRouteClaim: null,
  };
}

export class FakeOpportunityExtractor implements OpportunityExtractor {
  readonly kind: ExtractorKind;
  readonly providerId: string | null;
  readonly modelId: string | null;
  readonly promptVersion: string | null;
  readonly #scenario: FakeExtractionScenario;

  constructor(
    scenario: FakeExtractionScenario,
    options: {
      readonly kind?: ExtractorKind;
      readonly providerId?: string | null;
      readonly modelId?: string | null;
      readonly promptVersion?: string | null;
    } = {},
  ) {
    this.#scenario = scenario;
    this.kind = options.kind ?? 'RULE';
    this.providerId = options.providerId ?? null;
    this.modelId = options.modelId ?? null;
    this.promptVersion = options.promptVersion ?? null;
  }

  async extract(input: ExtractionInput): Promise<ExtractorOutput> {
    const base = baseCandidate(input);
    let candidate: CandidateOpportunity;
    let evidence: readonly EvidenceBinding[];

    switch (this.#scenario) {
      case 'FIXED_SURVEY': {
        candidate = {
          ...base,
          title: 'Paid research survey',
          opportunityCategory: 'MARKET_RESEARCH',
          incomeLadderLevel: 'TASK_WORK',
          compensationType: 'FIXED',
          advertisedCompensationValue: 12,
          expectedPayoutValue: 12,
          compensationCurrency: 'USD',
          applicationRequired: false,
          qualificationRequired: true,
          canonicalDestinationUrl: 'https://example.invalid/study',
          immediateTodayRouteClaim: false,
        };
        evidence = [
          binding(input.snapshot.id, 'title', candidate.title),
          binding(input.snapshot.id, 'opportunityCategory', candidate.opportunityCategory),
          binding(input.snapshot.id, 'incomeLadderLevel', candidate.incomeLadderLevel),
          binding(input.snapshot.id, 'compensationType', candidate.compensationType),
          binding(input.snapshot.id, 'advertisedCompensationValue', 12),
          binding(input.snapshot.id, 'expectedPayoutValue', 12),
          binding(input.snapshot.id, 'compensationCurrency', 'USD'),
          binding(input.snapshot.id, 'applicationRequired', false),
          binding(input.snapshot.id, 'qualificationRequired', true),
          binding(input.snapshot.id, 'canonicalDestinationUrl', candidate.canonicalDestinationUrl),
        ];
        break;
      }
      case 'DRAW_MAXIMUM': {
        candidate = {
          ...base,
          title: 'Prize draw with advertised maximum',
          opportunityCategory: 'PROMOTION',
          incomeLadderLevel: 'MICRO_REWARD',
          compensationType: 'DRAW',
          advertisedCompensationValue: 500,
          expectedPayoutValue: null,
          compensationCurrency: 'USD',
          applicationRequired: false,
          qualificationRequired: false,
          immediateTodayRouteClaim: false,
        };
        evidence = [
          binding(input.snapshot.id, 'title', candidate.title),
          binding(input.snapshot.id, 'opportunityCategory', candidate.opportunityCategory),
          binding(input.snapshot.id, 'incomeLadderLevel', candidate.incomeLadderLevel),
          binding(input.snapshot.id, 'compensationType', candidate.compensationType),
          binding(input.snapshot.id, 'advertisedCompensationValue', 500),
          binding(input.snapshot.id, 'compensationCurrency', 'USD'),
          binding(input.snapshot.id, 'applicationRequired', false),
          binding(input.snapshot.id, 'qualificationRequired', false),
        ];
        break;
      }
      case 'UNKNOWN_COMPENSATION': {
        candidate = {
          ...base,
          title: 'Opportunity with compensation not stated',
          opportunityCategory: 'MICROTASK',
          incomeLadderLevel: 'TASK_WORK',
          compensationType: 'OTHER',
        };
        evidence = [
          binding(input.snapshot.id, 'title', candidate.title),
          binding(input.snapshot.id, 'opportunityCategory', candidate.opportunityCategory),
          binding(input.snapshot.id, 'incomeLadderLevel', candidate.incomeLadderLevel),
          binding(input.snapshot.id, 'compensationType', candidate.compensationType),
        ];
        break;
      }
      case 'AI_WORK_QUALIFIED': {
        candidate = {
          ...base,
          title: 'AI evaluation task after qualification',
          opportunityCategory: 'AI_EVALUATION',
          incomeLadderLevel: 'TASK_WORK',
          compensationType: 'PER_TASK',
          advertisedCompensationValue: 20,
          expectedPayoutValue: 20,
          compensationCurrency: 'USD',
          applicationRequired: true,
          qualificationRequired: true,
          applicationMinutes: 10,
          qualificationScreeningMinutes: 15,
          estimatedActiveMinutes: 30,
          eligibleCountriesOrRegions: ['KR', 'US'],
          languageRequirements: ['en'],
          skillRequirements: ['reasoning'],
          immediateTodayRouteClaim: false,
        };
        evidence = [
          binding(input.snapshot.id, 'title', candidate.title),
          binding(input.snapshot.id, 'opportunityCategory', candidate.opportunityCategory),
          binding(input.snapshot.id, 'incomeLadderLevel', candidate.incomeLadderLevel),
          binding(input.snapshot.id, 'compensationType', candidate.compensationType),
          binding(input.snapshot.id, 'advertisedCompensationValue', 20),
          binding(input.snapshot.id, 'expectedPayoutValue', 20),
          binding(input.snapshot.id, 'compensationCurrency', 'USD'),
          binding(input.snapshot.id, 'applicationRequired', true),
          binding(input.snapshot.id, 'qualificationRequired', true),
          binding(input.snapshot.id, 'applicationMinutes', 10),
          binding(input.snapshot.id, 'qualificationScreeningMinutes', 15),
          binding(input.snapshot.id, 'estimatedActiveMinutes', 30),
          binding(input.snapshot.id, 'eligibleCountriesOrRegions', ['KR', 'US']),
          binding(input.snapshot.id, 'languageRequirements', ['en']),
          binding(input.snapshot.id, 'skillRequirements', ['reasoning']),
        ];
        break;
      }
      case 'CONFLICTING_COMPENSATION': {
        candidate = {
          ...base,
          title: 'Conflicting compensation source text',
          opportunityCategory: 'SURVEY',
          incomeLadderLevel: 'TASK_WORK',
          compensationType: 'VARIABLE',
          advertisedCompensationValue: 10,
          expectedPayoutValue: null,
          compensationCurrency: 'USD',
        };
        evidence = [
          binding(input.snapshot.id, 'title', candidate.title),
          binding(input.snapshot.id, 'opportunityCategory', candidate.opportunityCategory),
          binding(input.snapshot.id, 'incomeLadderLevel', candidate.incomeLadderLevel),
          binding(input.snapshot.id, 'compensationType', candidate.compensationType),
          binding(input.snapshot.id, 'advertisedCompensationValue', 10, true),
          binding(input.snapshot.id, 'advertisedCompensationValue', 15, true),
          binding(input.snapshot.id, 'compensationCurrency', 'USD'),
        ];
        break;
      }
      case 'STALE_SOURCE': {
        candidate = {
          ...base,
          title: 'Stale source fixture',
          opportunityCategory: 'MICROTASK',
          incomeLadderLevel: 'TASK_WORK',
          compensationType: 'OTHER',
          sourceFreshness: 'STALE',
        };
        evidence = [
          binding(input.snapshot.id, 'title', candidate.title),
          binding(input.snapshot.id, 'opportunityCategory', candidate.opportunityCategory),
          binding(input.snapshot.id, 'incomeLadderLevel', candidate.incomeLadderLevel),
          binding(input.snapshot.id, 'compensationType', candidate.compensationType),
        ];
        break;
      }
      case 'MALFORMED_NEGATIVE': {
        candidate = {
          ...base,
          title: 'Malformed negative payout fixture',
          opportunityCategory: 'SURVEY',
          incomeLadderLevel: 'TASK_WORK',
          compensationType: 'FIXED',
          advertisedCompensationValue: -1,
          compensationCurrency: 'USD',
        };
        evidence = [
          binding(input.snapshot.id, 'title', candidate.title),
          binding(input.snapshot.id, 'opportunityCategory', candidate.opportunityCategory),
          binding(input.snapshot.id, 'incomeLadderLevel', candidate.incomeLadderLevel),
          binding(input.snapshot.id, 'compensationType', candidate.compensationType),
          binding(input.snapshot.id, 'advertisedCompensationValue', -1),
          binding(input.snapshot.id, 'compensationCurrency', 'USD'),
        ];
        break;
      }
      case 'MISSING_EVIDENCE': {
        candidate = {
          ...base,
          title: 'Missing evidence fixture',
          opportunityCategory: 'SURVEY',
          incomeLadderLevel: 'TASK_WORK',
          compensationType: 'FIXED',
          advertisedCompensationValue: 8,
          compensationCurrency: 'USD',
        };
        evidence = [binding(input.snapshot.id, 'title', candidate.title)];
        break;
      }
    }

    const rawStructuredOutputHash = hash(JSON.stringify({ candidate, evidence }));
    return Object.freeze({ candidate: Object.freeze(candidate), evidence: Object.freeze([...evidence]), rawStructuredOutputHash });
  }
}
