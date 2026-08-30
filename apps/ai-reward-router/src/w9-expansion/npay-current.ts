import type {
  EarningOpportunity,
  OpportunityCompensationComponent,
  OpportunityEvidence,
  OpportunityRequirement,
  OpportunityVersion,
  OpportunityWindow,
  ReviewDecisionRecord,
  ReviewQueueItem,
  SourceSnapshot,
} from '../persistence/domain.js';
import type { SourceCollectionGate, SourcePolicyReview } from '../source-policy/domain.js';
import { sourceById } from '../source-policy/registry.js';
import { stableEvidenceHash } from '../verified20/hash.js';
import type { CertaintyType } from '../verified20/domain.js';
import type { W9ExpansionRecord } from './domain.js';

export const NPAY_W9_OBSERVED_AT = '2026-08-30T10:23:00.000Z';
const termsUrl = 'https://policy.naver.com/policy/service.html';

export const NPAY_W9_POLICY: SourcePolicyReview = Object.freeze({
  sourceId: 'SRC-NPAY',
  robotsStatus: 'WAIVED_MANUAL_ZERO_PRODUCT_TRANSPORT',
  termsStatus: 'REVIEWED_NAVER_SERVICE_TERMS_AND_OFFICIAL_NPAY_EVENT_PAGES_2026-08-30',
  commercialReuse: 'LIMITED',
  textReuse: 'LIMITED',
  imageLogoReuse: 'BLOCKED',
  automationPermission: 'BLOCKED',
  affiliateIncentive: 'UNKNOWN',
  policyEvidenceUrl: termsUrl,
  reviewedAt: NPAY_W9_OBSERVED_AT,
  reviewer: 'CENTRAL',
  decision: 'PASS_WITH_LIMITS',
  notes: 'Manual factual event metadata and canonical official links only. Naver terms preserve content/IP rights and prohibit unauthorized automation. B64 does not reproduce event-page expressive text, images or logos, does not crawl Naver, and does not treat public visibility as a blanket content license. Each record is a short B64-authored factual normalization of public dates, spend conditions and reward mechanics.',
});

interface Config {
  readonly ordinal: number;
  readonly slug: string;
  readonly title: string;
  readonly url: string;
  readonly merchant: string;
  readonly category: 'CASHBACK' | 'PROMOTION';
  readonly certaintyType: CertaintyType;
  readonly rewardAmount: number | null;
  readonly rewardPercent: number | null;
  readonly rewardCap: number | null;
  readonly minSpend: number | null;
  readonly startAt: string;
  readonly endAt: string;
  readonly payoutRule: string | null;
  readonly participation: string;
  readonly extraRequirements: readonly string[];
  readonly drawWinners: number | null;
}

const CONFIGS: readonly Config[] = Object.freeze([
  Object.freeze({
    ordinal: 24,
    slug: 'compuzone-aug-40k',
    title: 'Npay — Computezone KRW 40,000 additional points',
    url: 'https://pay.naver.com/member/notice/200021876?headerType=back',
    merchant: 'Computezone',
    category: 'CASHBACK',
    certaintyType: 'CONDITIONAL',
    rewardAmount: 40000,
    rewardPercent: null,
    rewardCap: null,
    minSpend: 2000000,
    startAt: '2026-08-07T00:00:00+09:00',
    endAt: '2026-08-31T23:59:59+09:00',
    payoutRule: null,
    participation: 'Pay at least KRW 2,000,000 through the qualifying Npay payment flow at Computezone during the event period.',
    extraRequirements: Object.freeze(['Real-name verified user; one benefit per person during the event period.']),
    drawWinners: null,
  }),
  Object.freeze({
    ordinal: 25,
    slug: 'nepa-aug-10pct',
    title: 'Npay — NEPA 10% points promotion',
    url: 'https://pay.naver.com/benefit/payment/detail/22873960757100',
    merchant: 'NEPA',
    category: 'CASHBACK',
    certaintyType: 'CONDITIONAL',
    rewardAmount: null,
    rewardPercent: 10,
    rewardCap: 50000,
    minSpend: 10000,
    startAt: '2026-08-01T00:00:00+09:00',
    endAt: '2026-08-31T23:59:59+09:00',
    payoutRule: null,
    participation: 'Spend at least KRW 10,000 using qualifying Npay points/money payment during the August event period.',
    extraRequirements: Object.freeze(['Public event states no participation-count limit, with total reward capped at KRW 50,000.']),
    drawWinners: null,
  }),
  Object.freeze({
    ordinal: 26,
    slug: 'dyson-photo-review-aug-30k',
    title: 'Npay — Dyson selected-product photo-review KRW 30,000 points',
    url: 'https://pay.naver.com/member/notice/200021897?headerType=back',
    merchant: 'Dyson Korea',
    category: 'PROMOTION',
    certaintyType: 'CONDITIONAL',
    rewardAmount: 30000,
    rewardPercent: null,
    rewardCap: null,
    minSpend: null,
    startAt: '2026-08-14T00:00:00+09:00',
    endAt: '2026-09-14T23:59:59+09:00',
    payoutRule: 'Purchase must occur by 2026-08-31; photo review may be submitted through 2026-09-14.',
    participation: 'Buy one of the specified eligible Dyson Airwrap products through Npay during the purchase window and submit a qualifying photo review during the review window.',
    extraRequirements: Object.freeze(['Selected products only; payment must remain uncancelled through the applicable reward conditions.']),
    drawWinners: null,
  }),
  Object.freeze({
    ordinal: 27,
    slug: 'ohou-aug-2k',
    title: 'Npay — Today House KRW 2,000 points on KRW 90,000 spend',
    url: 'https://pay.naver.com/member/notice/200021825?headerType=back',
    merchant: 'Today House',
    category: 'CASHBACK',
    certaintyType: 'CONDITIONAL',
    rewardAmount: 2000,
    rewardPercent: null,
    rewardCap: null,
    minSpend: 90000,
    startAt: '2026-08-17T00:00:00+09:00',
    endAt: '2026-08-31T23:59:59+09:00',
    payoutRule: 'Official notice states payout during 2026-09-30 for qualifying uncancelled payment.',
    participation: 'Spend at least KRW 90,000 at Today House using the qualifying Npay path during the event period.',
    extraRequirements: Object.freeze(['Real-name verification basis; one benefit per person; may end early if budget is exhausted.']),
    drawWinners: null,
  }),
  Object.freeze({
    ordinal: 28,
    slug: 'ohou-aug-draw-12k',
    title: 'Npay — Today House KRW 12,000 points draw',
    url: 'https://pay.naver.com/member/notice/200021824?headerType=back',
    merchant: 'Today House',
    category: 'PROMOTION',
    certaintyType: 'DRAW',
    rewardAmount: 12000,
    rewardPercent: null,
    rewardCap: null,
    minSpend: null,
    startAt: '2026-08-01T00:00:00+09:00',
    endAt: '2026-08-31T23:59:59+09:00',
    payoutRule: 'Official notice states payout during 2026-09-28 to winners whose qualifying payment remains uncancelled.',
    participation: 'Make a qualifying Npay payment at Today House during the August event period to enter the points draw.',
    extraRequirements: Object.freeze(['Real-name verification basis; one entry per person during the period.']),
    drawWinners: 1200,
  }),
]);

function gates(config: Config, reviewId: string): readonly SourceCollectionGate[] {
  const g = (i: number, gate: string, status: SourceCollectionGate['status'], evidence: string, notes: string): SourceCollectionGate => Object.freeze({
    gateId: `SRC-NPAY-W9-${config.ordinal}-G${i}`,
    sourceId: 'SRC-NPAY',
    gate,
    required: true,
    status,
    failureAction: i <= 4 ? 'BLOCK' : 'SHADOW',
    evidence,
    notes,
  });
  return Object.freeze([
    g(1, 'Source identity verified', 'PASS', config.url, 'Exact official Naver Pay event page identifies the provider and event.'),
    g(2, 'Official endpoint identified', 'PASS', config.url, 'Only the exact official public event page is used; no member/private endpoint is accessed.'),
    g(3, 'robots reviewed', 'WAIVED', 'MANUAL_ZERO_PRODUCT_TRANSPORT', 'No B64 automated Naver collector is authorized or used.'),
    g(4, 'terms/commercial boundary reviewed', 'PASS', termsUrl, 'Bounded factual metadata and canonical link only; no Naver content/IP license or automation permission is inferred.'),
    g(5, 'collector stability test', 'WAIVED', 'NO_AUTOMATED_COLLECTOR', 'Not applicable to manual curation.'),
    g(6, 'evidence extraction works', 'PASS', `W9_NPAY_${config.ordinal}_FIELD_EVIDENCE`, 'Reward, conditions and dates are bound to the exact official event page.'),
    g(7, 'change detection works', 'PASS', 'W6_VERSIONING_AND_EVENT_END_STATE', 'Event end/early-termination states must suppress or version the opportunity on later checks.'),
    g(8, 'human review accepted sample', 'PASS', reviewId, 'CENTRAL reviewed this exact event representation.'),
  ]);
}

function createRecord(config: Config): W9ExpansionRecord {
  const snapshotId = `snapshot-w9-npay-${config.slug}-20260830`;
  const opportunityId = `opp-w9-npay-${config.slug}`;
  const versionId = `${opportunityId}-v1`;
  const reviewId = `review-w9-npay-${config.slug}-v1`;
  const rawPayload = Object.freeze({
    merchant: config.merchant,
    title: config.title,
    rewardAmount: config.rewardAmount,
    rewardPercent: config.rewardPercent,
    rewardCap: config.rewardCap,
    minimumSpend: config.minSpend,
    eventStart: config.startAt,
    eventEnd: config.endAt,
    payoutRule: config.payoutRule,
    participation: config.participation,
    extraRequirements: config.extraRequirements,
    drawWinners: config.drawWinners,
    guaranteedExpectedValue: null,
  });
  const contentHash = stableEvidenceHash(rawPayload);
  const snapshot: SourceSnapshot = Object.freeze({
    id: snapshotId,
    sourceId: 'SRC-NPAY',
    endpointId: null,
    acquiredAt: NPAY_W9_OBSERVED_AT,
    acquisitionModeUsed: sourceById('SRC-NPAY').acquisitionMode,
    canonicalUrl: config.url,
    contentType: 'application/json',
    rawLocation: null,
    rawPayload,
    contentHash,
    fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, privateAccountAccess: false }),
    actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }),
    httpStatus: null,
  });
  const opportunity: EarningOpportunity = Object.freeze({
    id: opportunityId,
    sourceId: 'SRC-NPAY',
    merchantId: config.merchant,
    canonicalKey: `SRC-NPAY:${config.slug}`,
    providerExternalKey: config.url.split('/').pop() ?? config.slug,
    lifecycleState: 'VERIFIED',
    currentVersionId: versionId,
    firstSeenAt: NPAY_W9_OBSERVED_AT,
    lastSeenAt: NPAY_W9_OBSERVED_AT,
  });
  const version: OpportunityVersion = Object.freeze({
    id: versionId,
    offerId: opportunityId,
    versionNumber: 1,
    sourceSnapshotId: snapshotId,
    title: config.title,
    shortSummary: `${config.participation} Advertised reward mechanics are preserved exactly; expected payout is not inferred, and draw outcomes are never guaranteed.`,
    originalLanguage: 'ko',
    verificationState: 'VERIFIED',
    sourceSnapshotHash: contentHash,
    modelId: null,
    promptVersion: null,
    inputHash: null,
    opportunityCategory: config.category,
    incomeLadderLevel: 'MICRO_REWARD',
    compensationType: config.certaintyType === 'DRAW' ? 'DRAW' : (config.rewardPercent === null ? 'FIXED' : 'VARIABLE'),
    advertisedCompensationValue: config.rewardAmount,
    expectedPayoutValue: null,
    compensationCurrency: 'KRW',
    estimatedActiveMinutes: null,
    estimatedTotalEffortMinutes: null,
    applicationMinutes: null,
    qualificationScreeningMinutes: null,
    preparationMinutes: null,
    startLatencyMinutes: null,
    payoutMethod: Object.freeze({ method: 'NPAY_POINTS' }),
    payoutDelay: config.payoutRule === null ? null : Object.freeze({ publicRule: config.payoutRule }),
    providerFees: null,
    repeatability: Object.freeze({ eventParticipation: config.certaintyType === 'DRAW' ? 'ONE_ENTRY_PER_PERSON' : 'EVENT_RULES_APPLY' }),
    supplyAvailabilityState: 'PUBLIC_PROMOTION_AVAILABLE',
    supplyObservedAt: NPAY_W9_OBSERVED_AT,
    applicationRequired: false,
    qualificationRequired: true,
    qualificationProbability: null,
    acceptanceProbability: config.certaintyType === 'DRAW' ? null : 1,
    rejectionOrReversalRisk: Object.freeze({ cancellationOrRuleViolationCanVoidReward: true }),
    payoutReliability: null,
    eligibleCountriesOrRegions: Object.freeze(['KOREA']),
    languageRequirements: null,
    skillRequirements: null,
    deviceOsRequirements: null,
    identityKycRequirements: Object.freeze(['REAL_NAME_VERIFICATION_WHERE_STATED']),
    ageRequirements: null,
    taxContractorRequirements: null,
    schedulingRequirements: null,
    canonicalDestinationUrl: config.url,
    createdAt: NPAY_W9_OBSERVED_AT,
  });

  const evidence = (suffix: string, fieldPath: string, text: string): OpportunityEvidence => {
    const locator = Object.freeze({ url: config.url, observationMode: 'OFFICIAL_PUBLIC_NPAY_EVENT' });
    return Object.freeze({
      id: `ev-w9-npay-${config.slug}-${suffix}`,
      offerVersionId: versionId,
      sourceSnapshotId: snapshotId,
      fieldPath,
      evidenceText: text,
      evidenceLocator: locator,
      evidenceHash: stableEvidenceHash({ fieldPath, text, locator }),
      confidence: 1,
      createdAt: NPAY_W9_OBSERVED_AT,
    });
  };
  const evidenceRows = Object.freeze([
    evidence('event', 'title', `Official Naver Pay page identifies the current ${config.merchant} event.`),
    evidence('reward', 'compensation', config.rewardPercent === null ? `Advertised Npay reward is KRW ${config.rewardAmount?.toLocaleString('en-US') ?? 'variable'}.` : `Advertised reward is ${config.rewardPercent}% with a KRW ${config.rewardCap?.toLocaleString('en-US')} cap.`),
    evidence('condition', 'requirements', config.participation),
    evidence('window', 'windows', `Public event window is ${config.startAt} through ${config.endAt}.`),
  ]);

  const requirements: OpportunityRequirement[] = [
    Object.freeze({
      id: `req-w9-npay-${config.slug}-participation`,
      offerVersionId: versionId,
      requirementType: 'OTHER',
      operator: 'REQUIRED',
      normalizedValue: Object.freeze({ merchant: config.merchant, minimumSpendKrw: config.minSpend, participation: config.participation, extra: config.extraRequirements }),
      displayText: config.participation,
      required: true,
      confidence: 1,
      evidenceId: evidenceRows[2]!.id,
    }),
  ];

  const compensation: OpportunityCompensationComponent = Object.freeze({
    id: `comp-w9-npay-${config.slug}`,
    offerVersionId: versionId,
    componentType: config.certaintyType === 'DRAW' ? 'PRIZE' : 'CASHBACK',
    amount: config.rewardAmount,
    currency: 'KRW',
    rateUnit: null,
    percent: config.rewardPercent,
    capAmount: config.rewardCap,
    conditionText: config.certaintyType === 'DRAW' ? `Draw reward; ${config.drawWinners ?? 'specified'} winners. Winning is not guaranteed.` : config.participation,
    evidenceId: evidenceRows[1]!.id,
  });

  const windows: OpportunityWindow[] = [
    Object.freeze({
      id: `window-w9-npay-${config.slug}-participation`,
      offerVersionId: versionId,
      windowType: 'PARTICIPATION',
      startAt: config.startAt,
      endAt: config.endAt,
      relativeRule: null,
      displayText: `Official participation period: ${config.startAt} through ${config.endAt}.`,
      evidenceId: evidenceRows[3]!.id,
    }),
  ];

  const queue: ReviewQueueItem = Object.freeze({
    id: `rq-w9-npay-${config.slug}-v1`,
    offerVersionId: versionId,
    reasonCodes: Object.freeze(['REAL_CURRENT_PUBLIC_REWARD','SPEND_OR_ACTION_CONDITION','DEADLINE_BOUND']),
    priority: 'HIGH',
    state: 'RESOLVED',
    assignedTo: 'CENTRAL',
    createdAt: NPAY_W9_OBSERVED_AT,
    resolvedAt: NPAY_W9_OBSERVED_AT,
  });
  const review: ReviewDecisionRecord = Object.freeze({
    id: reviewId,
    reviewQueueId: queue.id,
    offerVersionId: versionId,
    decision: 'APPROVE',
    reviewerId: 'CENTRAL',
    approvalReason: 'Exact official Naver Pay event evidence supports the current reward amount/rate, participation condition and event window. Expected value is not inferred; draw outcome is not guaranteed; later early termination or end-state must suppress/version the record.',
    rejectionReason: null,
    patch: null,
    createdAt: NPAY_W9_OBSERVED_AT,
  });

  return Object.freeze({
    ordinal: config.ordinal,
    realEvidence: true,
    syntheticFixture: false,
    sourcePolicy: NPAY_W9_POLICY,
    sourceGates: gates(config, reviewId),
    snapshot,
    opportunity,
    version,
    certaintyType: config.certaintyType,
    requirements: Object.freeze(requirements),
    compensationComponents: Object.freeze([compensation]),
    windows: Object.freeze(windows),
    evidence: evidenceRows,
    reviewQueue: queue,
    reviewDecision: review,
    criticalEvidenceIds: Object.freeze(evidenceRows.map((item) => item.id)),
    lastCheckedAt: NPAY_W9_OBSERVED_AT,
    supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
  });
}

export const NPAY_CURRENT_W9_RECORDS: readonly W9ExpansionRecord[] = Object.freeze(CONFIGS.map(createRecord));
