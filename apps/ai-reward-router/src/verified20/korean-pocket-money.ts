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
import type { Source, SourceCollectionGate, SourcePolicyReview } from '../source-policy/domain.js';
import type { Verified20Record } from './domain.js';
import { stableEvidenceHash } from './hash.js';

export const KOREAN_POCKET_MONEY_OBSERVED_AT = '2026-08-30T10:23:00.000Z';

const RAKUTEN_ABOUT = 'https://member.insight.rakuten.kr/about';
const RAKUTEN_REWARDS = 'https://member.insight.rakuten.kr/points-rewards';
const RAKUTEN_TERMS = 'https://member.insight.rakuten.kr/policies';
const PANELPOWER_HOME = 'https://www.panel.co.kr/';
const PANELPOWER_APP = 'https://www.panel.co.kr/app/';
const IPSOS_HOME = 'https://www.ipsosisay.com/ko-kr';
const IPSOS_REWARDS = 'https://www.ipsosisay.com/ko-kr/rewards';
const IPSOS_TERMS = 'https://www.ipsosisay.com/ko-kr/terms-and-conditions';
const LIFEPOINTS_HOME = 'https://www.lifepointspanel.com/ko-kr/find-out-more';
const GOOGLE_ELIGIBILITY = 'https://support.google.com/opinionrewards/answer/6322274?hl=ko';
const GOOGLE_CREDITS = 'https://support.google.com/opinionrewards/answer/6322284?hl=ko';

const source = (value: Source): Source => Object.freeze(value);

export const KOREAN_POCKET_MONEY_SOURCES = Object.freeze({
  RAKUTEN: source({ sourceId: 'SRC-RAKUTEN-INSIGHT-KR', sourceName: 'Rakuten Insight Korea', sourceType: 'MARKET_RESEARCH_PANEL', lane: 'BUILD', launchPriority: 'P1', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: false, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'LOW', updateCadence: 'WEEKLY', officialBaseUrl: 'https://member.insight.rakuten.kr/', listUrl: RAKUTEN_ABOUT, nextAction: 'Track public panel/reward terms only; never infer individual survey inventory.', notes: 'Pocket-money survey panel; manual factual curation only.', acquisitionMode: 'DEEP_LINK_OR_DIRECTORY', opportunityClassHint: Object.freeze(['SURVEY','MARKET_RESEARCH']) }),
  PANELPOWER: source({ sourceId: 'SRC-PANELPOWER', sourceName: 'Embrain PanelPower', sourceType: 'MARKET_RESEARCH_PANEL', lane: 'BUILD', launchPriority: 'P1', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: true, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'LOW', updateCadence: 'DAILY', officialBaseUrl: PANELPOWER_HOME, listUrl: PANELPOWER_HOME, nextAction: 'Track panel program and public short research opportunities; suppress ended detail pages.', notes: 'Pocket-money survey panel plus bounded paid research.', acquisitionMode: 'DEEP_LINK_OR_DIRECTORY', opportunityClassHint: Object.freeze(['SURVEY','MARKET_RESEARCH']) }),
  IPSOS: source({ sourceId: 'SRC-IPSOS-ISAY-KR', sourceName: 'Ipsos iSay Korea', sourceType: 'MARKET_RESEARCH_PANEL', lane: 'BUILD', launchPriority: 'P1', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: false, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'LOW', updateCadence: 'WEEKLY', officialBaseUrl: IPSOS_HOME, listUrl: IPSOS_HOME, nextAction: 'Track public panel/reward facts; never capture survey questionnaires or confidential research content.', notes: 'Pocket-money survey panel; manual factual curation only.', acquisitionMode: 'DEEP_LINK_OR_DIRECTORY', opportunityClassHint: Object.freeze(['SURVEY']) }),
  LIFEPOINTS: source({ sourceId: 'SRC-LIFEPOINTS-KR', sourceName: 'LifePoints Korea', sourceType: 'MARKET_RESEARCH_PANEL', lane: 'BUILD', launchPriority: 'P2', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: false, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'LOW', updateCadence: 'WEEKLY', officialBaseUrl: 'https://www.lifepointspanel.com/ko-kr', listUrl: LIFEPOINTS_HOME, nextAction: 'Track public reward mechanics only; no member dashboard or individual survey inventory.', notes: 'Pocket-money survey panel; manual factual curation only.', acquisitionMode: 'DEEP_LINK_OR_DIRECTORY', opportunityClassHint: Object.freeze(['SURVEY']) }),
  GOOGLE: source({ sourceId: 'SRC-GOOGLE-OPINION-REWARDS-KR', sourceName: 'Google Opinion Rewards Korea', sourceType: 'REWARD_SURVEY_APP', lane: 'BUILD', launchPriority: 'P1', country: 'KR', accessMode: 'PUBLIC_HELP_AND_APP', loginRequired: true, jsRendered: false, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'LOW', updateCadence: 'WEEKLY', officialBaseUrl: 'https://support.google.com/opinionrewards/', listUrl: GOOGLE_ELIGIBILITY, nextAction: 'Track Android Korea eligibility/reward rules; survey frequency remains unknown.', notes: 'Pocket-money reward app; manual factual curation only.', acquisitionMode: 'DEEP_LINK_OR_DIRECTORY', opportunityClassHint: Object.freeze(['SURVEY']) }),
}) satisfies Readonly<Record<string, Source>>;

type Key = keyof typeof KOREAN_POCKET_MONEY_SOURCES;

function policy(key: Key, evidenceUrl: string, notes: string): SourcePolicyReview {
  const s = KOREAN_POCKET_MONEY_SOURCES[key];
  return Object.freeze({ sourceId: s.sourceId, robotsStatus: 'WAIVED_MANUAL_ZERO_PRODUCT_TRANSPORT', termsStatus: 'REVIEWED_PUBLIC_MEMBER_REWARD_BOUNDARY_2026-08-30', commercialReuse: 'LIMITED', textReuse: 'LIMITED', imageLogoReuse: 'BLOCKED', automationPermission: 'BLOCKED', affiliateIncentive: 'UNKNOWN', policyEvidenceUrl: evidenceUrl, reviewedAt: KOREAN_POCKET_MONEY_OBSERVED_AT, reviewer: 'CENTRAL', decision: 'PASS_WITH_LIMITS', notes });
}

export const KOREAN_POCKET_MONEY_POLICIES: Readonly<Record<Key, SourcePolicyReview>> = Object.freeze({
  RAKUTEN: policy('RAKUTEN', RAKUTEN_TERMS, 'Manual factual paraphrase and canonical links only. Do not reproduce surveys, member-only inventory, logos, or automate acquisition. Public terms confirm Korea membership and variable survey rewards but are not treated as a blanket content license.'),
  PANELPOWER: policy('PANELPOWER', PANELPOWER_HOME, 'Manual factual paraphrase of public panel/research facts and canonical links only. No survey questionnaires, member data, logos, bulk copying, or automated acquisition.'),
  IPSOS: policy('IPSOS', IPSOS_TERMS, 'Manual factual paraphrase and canonical links only. Do not reproduce Ipsos intellectual property, confidential survey/research content, member data, logos, or automate acquisition.'),
  LIFEPOINTS: policy('LIFEPOINTS', LIFEPOINTS_HOME, 'Manual factual paraphrase of public program/reward mechanics and canonical links only. No private/member survey inventory, questionnaire content, logos, bulk copying, or automation.'),
  GOOGLE: policy('GOOGLE', GOOGLE_ELIGIBILITY, 'Manual factual paraphrase of official eligibility and reward-help facts only. No app/account data, logos, survey content, or automated acquisition.'),
});

function gates(key: Key, endpoint: string, reviewEvidence: string): readonly SourceCollectionGate[] {
  const s = KOREAN_POCKET_MONEY_SOURCES[key];
  const p = KOREAN_POCKET_MONEY_POLICIES[key];
  const g = (i: number, gate: string, status: SourceCollectionGate['status'], evidence: string, notes: string): SourceCollectionGate => Object.freeze({ gateId: `${s.sourceId}-G${i}`, sourceId: s.sourceId, gate, required: true, status, failureAction: i <= 4 ? 'BLOCK' : 'SHADOW', evidence, notes });
  return Object.freeze([
    g(1, 'Source identity verified', 'PASS', s.officialBaseUrl ?? endpoint, 'Official public provider surface identifies the program.'),
    g(2, 'Official endpoint identified', 'PASS', endpoint, 'Only public official program/reward/research pages are used.'),
    g(3, 'robots reviewed', 'WAIVED', 'MANUAL_ZERO_PRODUCT_TRANSPORT', 'No B64 automated collector is authorized or used.'),
    g(4, 'terms/commercial boundary reviewed', 'PASS', p.policyEvidenceUrl ?? endpoint, 'Bounded B64-authored factual paraphrase and canonical links only; no blanket reuse license is asserted.'),
    g(5, 'collector stability test', 'WAIVED', 'NO_AUTOMATED_COLLECTOR', 'Not applicable to manual/deep-link curation.'),
    g(6, 'evidence extraction works', 'PASS', `W8_${s.sourceId}_FIELD_EVIDENCE`, 'Counted record binds normalized fields to public official evidence.'),
    g(7, 'change detection works', 'WAIVED', 'FIRST_BASELINE_W6_AVAILABLE', 'First real baseline; future material changes use W6 versioning/suppression.'),
    g(8, 'human review accepted sample', 'PASS', reviewEvidence, 'CENTRAL reviewed the exact bounded representation before VERIFIED status.'),
  ]);
}

const GATES = Object.freeze({
  RAKUTEN: gates('RAKUTEN', RAKUTEN_REWARDS, 'review-w8-rakuten-insight-kr-v1'),
  PANELPOWER: gates('PANELPOWER', PANELPOWER_HOME, 'review-w8-panelpower-program-v1 | review-w8-panelpower-airdresser-v1'),
  IPSOS: gates('IPSOS', IPSOS_HOME, 'review-w8-ipsos-isay-kr-v1'),
  LIFEPOINTS: gates('LIFEPOINTS', LIFEPOINTS_HOME, 'review-w8-lifepoints-kr-v1'),
  GOOGLE: gates('GOOGLE', GOOGLE_ELIGIBILITY, 'review-w8-google-opinion-rewards-kr-v1'),
});

interface ProviderConfig {
  readonly slot: number;
  readonly key: Key;
  readonly slug: string;
  readonly title: string;
  readonly canonicalUrl: string;
  readonly summary: string;
  readonly rawFacts: unknown;
  readonly requirements: readonly Readonly<{ type: OpportunityRequirement['requirementType']; operator: string; value: unknown; text: string; url: string }>[];
  readonly compensationText: string;
  readonly payoutMethod: unknown;
  readonly evidenceRows: readonly Readonly<{ suffix: string; field: string; text: string; url: string }>[];
}

function providerRecord(c: ProviderConfig): Verified20Record {
  const s = KOREAN_POCKET_MONEY_SOURCES[c.key];
  const snapshotId = `snapshot-w8-${c.slug}-20260830`;
  const oppId = `opp-w8-${c.slug}`;
  const versionId = `${oppId}-v1`;
  const rawPayload = Object.freeze({ provider: s.sourceName, program: c.title, ...((c.rawFacts ?? {}) as object), individualSurveyInventoryObserved: false, selectionProbability: null, guaranteedSurveyFrequency: null });
  const snapshotHash = stableEvidenceHash(rawPayload);
  const snapshot: SourceSnapshot = Object.freeze({ id: snapshotId, sourceId: s.sourceId, endpointId: null, acquiredAt: KOREAN_POCKET_MONEY_OBSERVED_AT, acquisitionModeUsed: s.acquisitionMode, canonicalUrl: c.canonicalUrl, contentType: 'application/json', rawLocation: null, rawPayload, contentHash: snapshotHash, fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, privateAccountAccess: false, individualSurveyInventoryObserved: false }), actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }), httpStatus: null });
  const opportunity: EarningOpportunity = Object.freeze({ id: oppId, sourceId: s.sourceId, merchantId: null, canonicalKey: `${s.sourceId}:${c.slug}`, providerExternalKey: c.slug, lifecycleState: 'VERIFIED', currentVersionId: versionId, firstSeenAt: KOREAN_POCKET_MONEY_OBSERVED_AT, lastSeenAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
  const version: OpportunityVersion = Object.freeze({ id: versionId, offerId: oppId, versionNumber: 1, sourceSnapshotId: snapshotId, title: c.title, shortSummary: c.summary, originalLanguage: 'ko', verificationState: 'VERIFIED', sourceSnapshotHash: snapshotHash, modelId: null, promptVersion: null, inputHash: null, opportunityCategory: 'SURVEY', incomeLadderLevel: 'MICRO_REWARD', compensationType: 'VARIABLE', advertisedCompensationValue: null, expectedPayoutValue: null, compensationCurrency: null, estimatedActiveMinutes: null, estimatedTotalEffortMinutes: null, applicationMinutes: null, qualificationScreeningMinutes: null, preparationMinutes: null, startLatencyMinutes: null, payoutMethod: c.payoutMethod, payoutDelay: null, providerFees: null, repeatability: Object.freeze({ surveyInvitations: 'VARIABLE_NOT_GUARANTEED' }), supplyAvailabilityState: 'PUBLIC_PROVIDER_PROGRAM_AVAILABLE', supplyObservedAt: KOREAN_POCKET_MONEY_OBSERVED_AT, applicationRequired: true, qualificationRequired: null, qualificationProbability: null, acceptanceProbability: null, rejectionOrReversalRisk: null, payoutReliability: null, eligibleCountriesOrRegions: Object.freeze(['KOREA']), languageRequirements: null, skillRequirements: null, deviceOsRequirements: null, identityKycRequirements: null, ageRequirements: null, taxContractorRequirements: null, schedulingRequirements: Object.freeze({ flexible: true, guaranteedSurveyFrequency: null }), canonicalDestinationUrl: c.canonicalUrl, createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
  const evidence: OpportunityEvidence[] = c.evidenceRows.map((row) => { const locator = Object.freeze({ url: row.url, observationMode: 'OFFICIAL_PUBLIC_PAGE' }); return Object.freeze({ id: `ev-w8-${c.slug}-${row.suffix}`, offerVersionId: versionId, sourceSnapshotId: snapshotId, fieldPath: row.field, evidenceText: row.text, evidenceLocator: locator, evidenceHash: stableEvidenceHash({ fieldPath: row.field, text: row.text, locator }), confidence: 1, createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT }); });
  const ev = (suffix: string) => evidence.find((x) => x.id.endsWith(`-${suffix}`))?.id ?? null;
  const requirements: OpportunityRequirement[] = c.requirements.map((r, i) => Object.freeze({ id: `req-w8-${c.slug}-${i + 1}`, offerVersionId: versionId, requirementType: r.type, operator: r.operator, normalizedValue: r.value, displayText: r.text, required: true, confidence: 1, evidenceId: evidence.find((x) => (x.evidenceLocator as { url?: string } | null)?.url === r.url)?.id ?? null }));
  const compensation: readonly OpportunityCompensationComponent[] = Object.freeze([Object.freeze({ id: `comp-w8-${c.slug}-variable`, offerVersionId: versionId, componentType: 'POINT', amount: null, currency: null, rateUnit: null, percent: null, capAmount: null, conditionText: c.compensationText, evidenceId: ev('reward') })]);
  const windows: readonly OpportunityWindow[] = Object.freeze([Object.freeze({ id: `window-w8-${c.slug}-participation`, offerVersionId: versionId, windowType: 'PARTICIPATION', startAt: null, endAt: null, relativeRule: 'PROGRAM_ACTIVE_SURVEY_INVITATIONS_VARIABLE', displayText: 'Public provider program is active; individual survey invitations and timing are not guaranteed.', evidenceId: ev('program') })]);
  const queue: ReviewQueueItem = Object.freeze({ id: `rq-w8-${c.slug}-v1`, offerVersionId: versionId, reasonCodes: Object.freeze(['REAL_PROVIDER_PROGRAM','VARIABLE_SURVEY_SUPPLY','NO_PRIVATE_INVENTORY']), priority: 'NORMAL', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT, resolvedAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
  const review: ReviewDecisionRecord = Object.freeze({ id: `review-w8-${c.slug}-v1`, reviewQueueId: queue.id, offerVersionId: versionId, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Official public evidence supports the provider-level Korea survey/reward program. Individual survey availability, per-survey amount, selection probability and guaranteed frequency remain NULL/UNKNOWN.', rejectionReason: null, patch: null, createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
  return Object.freeze({ slot: c.slot, realEvidence: true, syntheticFixture: false, sourcePolicy: KOREAN_POCKET_MONEY_POLICIES[c.key], sourceGates: GATES[c.key], snapshot, opportunity, version, certaintyType: 'CONDITIONAL', requirements: Object.freeze(requirements), compensationComponents: compensation, windows, evidence: Object.freeze(evidence), reviewQueue: queue, reviewDecision: review, criticalEvidenceIds: Object.freeze(c.evidenceRows.map((r) => `ev-w8-${c.slug}-${r.suffix}`)), lastCheckedAt: KOREAN_POCKET_MONEY_OBSERVED_AT, supplyClaimMode: 'PROVIDER_PROGRAM_ONLY' });
}

export const RAKUTEN_INSIGHT_KR_RECORD = providerRecord({
  slot: 15, key: 'RAKUTEN', slug: 'rakuten-insight-kr-surveys', title: 'Rakuten Insight Korea — paid online surveys', canonicalUrl: RAKUTEN_ABOUT,
  summary: 'Rakuten Insight Korea publicly operates a Korea survey panel where members earn variable points for surveys and may exchange points for cash transfer, Naver Pay, donation or Cultureland rewards. No individual survey inventory or amount is asserted.',
  rawFacts: Object.freeze({ minimumAge: 16, residence: 'Korea', rewards: Object.freeze({ cashTransferFromKrw: 3000, naverPayFromKrw: 5000, culturelandFromKrw: 5000 }), perSurveyPoints: 'VARIABLE' }),
  requirements: Object.freeze([{ type: 'AGE', operator: 'GTE', value: 16, text: 'Member terms require age 16 or older.', url: RAKUTEN_TERMS }, { type: 'COUNTRY_REGION', operator: 'IN', value: Object.freeze(['KOREA']), text: 'Member terms require residence in South Korea.', url: RAKUTEN_TERMS }]),
  compensationText: 'Points vary by survey; public rewards include cash transfer from KRW 3,000 and Naver Pay from KRW 5,000. No universal per-survey amount is claimed.', payoutMethod: Object.freeze({ methods: Object.freeze(['BANK_TRANSFER','NAVER_PAY','CULTURELAND','DONATION']), thresholds: Object.freeze({ bankTransferKrw: 3000, naverPayKrw: 5000, culturelandKrw: 5000 }) }),
  evidenceRows: Object.freeze([{ suffix: 'program', field: 'title', text: 'Official Korea page identifies Rakuten Insight Surveys as an online survey platform that rewards members for survey participation.', url: RAKUTEN_ABOUT }, { suffix: 'eligibility', field: 'eligibleCountriesOrRegions', text: 'Official member terms require South Korea residence and age 16 or older.', url: RAKUTEN_TERMS }, { suffix: 'reward', field: 'payoutMethod', text: 'Official rewards page shows variable survey points exchangeable for cash transfer, Naver Pay, donation and Cultureland rewards.', url: RAKUTEN_REWARDS }]),
});

export const PANELPOWER_PROGRAM_RECORD = providerRecord({
  slot: 16, key: 'PANELPOWER', slug: 'panelpower-survey-program', title: 'Embrain PanelPower — surveys and reward balance', canonicalUrl: PANELPOWER_APP,
  summary: 'PanelPower publicly offers surveys and app missions that accumulate reward balance usable for cash and gift-certificate options. Individual survey supply and per-survey amounts are variable and are not asserted.',
  rawFacts: Object.freeze({ rewards: Object.freeze(['CASH','GIFT_CERTIFICATES']), surveyNotifications: true, appMissions: true, perSurveyAmount: null }),
  requirements: Object.freeze([{ type: 'OTHER', operator: 'REQUIRED', value: Object.freeze({ panelMembership: true }), text: 'Participation uses PanelPower panel membership/app.', url: PANELPOWER_APP }]),
  compensationText: 'Survey participation accumulates reward balance; cash and gift-certificate use is public. No universal per-survey amount is claimed.', payoutMethod: Object.freeze({ methods: Object.freeze(['CASH','GIFT_CERTIFICATE']) }),
  evidenceRows: Object.freeze([{ suffix: 'program', field: 'title', text: 'Official PanelPower app page states that survey participation accumulates reward balance.', url: PANELPOWER_APP }, { suffix: 'reward', field: 'payoutMethod', text: 'Official PanelPower page states accumulated rewards can be used for cash and gift certificates.', url: PANELPOWER_APP }]),
});

export const IPSOS_ISAY_KR_RECORD = providerRecord({
  slot: 17, key: 'IPSOS', slug: 'ipsos-isay-kr-surveys', title: 'Ipsos iSay Korea — survey points and rewards', canonicalUrl: IPSOS_HOME,
  summary: 'Ipsos iSay Korea publicly invites Korea panel members to surveys, awards points for participation and provides reward exchanges such as Naver Pay and gift certificates. Survey matching and per-survey rewards remain variable.',
  rawFacts: Object.freeze({ minimumAge: 14, residence: 'Korea', rewardsExamples: Object.freeze({ naverPayKrw2000Points: 200, naverPayKrw5000Points: 500 }), surveyCountGuaranteed: false }),
  requirements: Object.freeze([{ type: 'AGE', operator: 'GTE', value: 14, text: 'Korea panel terms require age 14 or older.', url: IPSOS_TERMS }, { type: 'COUNTRY_REGION', operator: 'IN', value: Object.freeze(['KOREA']), text: 'Korea panel terms require South Korea residence.', url: IPSOS_TERMS }]),
  compensationText: 'Points are earned through survey participation and can be exchanged for listed rewards; per-survey points vary and are not guaranteed.', payoutMethod: Object.freeze({ methods: Object.freeze(['NAVER_PAY','MOBILE_GIFT_CERTIFICATE','RETAIL_REWARD']) }),
  evidenceRows: Object.freeze([{ suffix: 'program', field: 'title', text: 'Official Korea page describes joining the survey community, receiving matched surveys and earning points.', url: IPSOS_HOME }, { suffix: 'eligibility', field: 'eligibleCountriesOrRegions', text: 'Official Korea terms require South Korea residence and age 14 or older.', url: IPSOS_TERMS }, { suffix: 'reward', field: 'payoutMethod', text: 'Official Korea rewards page lists point exchanges including Naver Pay and multiple gift/reward options.', url: IPSOS_REWARDS }]),
});

export const LIFEPOINTS_KR_RECORD = providerRecord({
  slot: 18, key: 'LIFEPOINTS', slug: 'lifepoints-kr-surveys', title: 'LifePoints Korea — rewarded online surveys', canonicalUrl: LIFEPOINTS_HOME,
  summary: 'LifePoints Korea publicly rewards completed online surveys with virtual LifePoints that can be exchanged for gift cards and PayPal credit. Individual survey inventory and points per survey remain variable.',
  rawFacts: Object.freeze({ rewards: Object.freeze(['GIFT_CARDS','PAYPAL_CREDIT']), typicalSurveyMinutes: '10-20', perSurveyPoints: null }),
  requirements: Object.freeze([{ type: 'OTHER', operator: 'REQUIRED', value: Object.freeze({ communityMembership: true }), text: 'Participation requires joining the LifePoints community.', url: LIFEPOINTS_HOME }]),
  compensationText: 'Completed surveys earn virtual LifePoints redeemable for gift cards and PayPal credit; no universal per-survey amount is claimed.', payoutMethod: Object.freeze({ methods: Object.freeze(['GIFT_CARD','PAYPAL_CREDIT']) }),
  evidenceRows: Object.freeze([{ suffix: 'program', field: 'title', text: 'Official Korea page states that members complete online market-research surveys and receive rewards.', url: LIFEPOINTS_HOME }, { suffix: 'reward', field: 'payoutMethod', text: 'Official Korea page states completed surveys earn points redeemable for gift cards and PayPal credit.', url: LIFEPOINTS_HOME }]),
});

function googleRecord(): Verified20Record {
  const base = providerRecord({
    slot: 19, key: 'GOOGLE', slug: 'google-opinion-rewards-kr-android', title: 'Google Opinion Rewards Korea — Android survey rewards', canonicalUrl: GOOGLE_ELIGIBILITY,
    summary: 'Google Opinion Rewards is currently available on Android in South Korea for eligible adults. Reward surveys provide Google Play credit; survey availability and reward amount vary, so expected payout and frequency remain unknown.',
    rawFacts: Object.freeze({ platform: 'ANDROID', country: 'Korea', minimumAge: 18, reward: 'GOOGLE_PLAY_CREDIT', surveyFrequency: null, rewardAmount: null }),
    requirements: Object.freeze([{ type: 'AGE', operator: 'GTE', value: 18, text: 'Official Korea help requires age 18 or older.', url: GOOGLE_ELIGIBILITY }, { type: 'COUNTRY_REGION', operator: 'IN', value: Object.freeze(['KOREA']), text: 'Android app is officially available in South Korea.', url: GOOGLE_ELIGIBILITY }, { type: 'OTHER', operator: 'REQUIRED', value: Object.freeze({ platform: 'ANDROID' }), text: 'This Korea record is specifically the Android availability path.', url: GOOGLE_ELIGIBILITY }]),
    compensationText: 'Reward surveys provide Google Play credit; the credited amount varies and survey availability is notification-based.', payoutMethod: Object.freeze({ method: 'GOOGLE_PLAY_CREDIT' }),
    evidenceRows: Object.freeze([{ suffix: 'program', field: 'title', text: 'Official help lists South Korea among countries where Google Opinion Rewards is available on Android.', url: GOOGLE_ELIGIBILITY }, { suffix: 'eligibility', field: 'ageRequirements', text: 'Official help states eligible users in available countries are age 18 or older.', url: GOOGLE_ELIGIBILITY }, { suffix: 'reward', field: 'payoutMethod', text: 'Official credit help states completed reward surveys credit the linked Google Play payments profile.', url: GOOGLE_CREDITS }]),
  });
  return Object.freeze({ ...base, version: Object.freeze({ ...base.version, deviceOsRequirements: Object.freeze(['ANDROID']) }) });
}
export const GOOGLE_OPINION_REWARDS_KR_RECORD = googleRecord();

export const PANELPOWER_AIRDRESSER_RECORD: Verified20Record = (() => {
  const s = KOREAN_POCKET_MONEY_SOURCES.PANELPOWER;
  const url = PANELPOWER_HOME;
  const snapshotId = 'snapshot-w8-panelpower-airdresser-20260830';
  const oppId = 'opp-w8-panelpower-airdresser-home-visit';
  const versionId = `${oppId}-v1`;
  const rawPayload = Object.freeze({ publicResearch: '2026 Samsung AirDresser purchaser home-visit interview', advertisedCompensationKrw: 300000, purchaserRequirement: '2026 model Samsung AirDresser purchaser', duration: null, deadline: null, acceptanceProbability: null });
  const hash = stableEvidenceHash(rawPayload);
  const snapshot: SourceSnapshot = Object.freeze({ id: snapshotId, sourceId: s.sourceId, endpointId: null, acquiredAt: KOREAN_POCKET_MONEY_OBSERVED_AT, acquisitionModeUsed: s.acquisitionMode, canonicalUrl: url, contentType: 'application/json', rawLocation: null, rawPayload, contentHash: hash, fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, privateAccountAccess: false }), actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }), httpStatus: null });
  const opportunity: EarningOpportunity = Object.freeze({ id: oppId, sourceId: s.sourceId, merchantId: null, canonicalKey: 'SRC-PANELPOWER:2026-airdresser-home-visit-interview', providerExternalKey: 'public-homepage-airdresser-20260830', lifecycleState: 'VERIFIED', currentVersionId: versionId, firstSeenAt: KOREAN_POCKET_MONEY_OBSERVED_AT, lastSeenAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
  const version: OpportunityVersion = Object.freeze({ id: versionId, offerId: oppId, versionNumber: 1, sourceSnapshotId: snapshotId, title: 'PanelPower — 2026 Samsung AirDresser purchaser home-visit interview', shortSummary: 'PanelPower currently lists a home-visit interview for purchasers of a 2026 Samsung AirDresser with advertised compensation of KRW 300,000. Duration, closing date and acceptance probability are not publicly asserted.', originalLanguage: 'ko', verificationState: 'VERIFIED', sourceSnapshotHash: hash, modelId: null, promptVersion: null, inputHash: null, opportunityCategory: 'MARKET_RESEARCH', incomeLadderLevel: 'PROJECT_WORK', compensationType: 'FIXED', advertisedCompensationValue: 300000, expectedPayoutValue: null, compensationCurrency: 'KRW', estimatedActiveMinutes: null, estimatedTotalEffortMinutes: null, applicationMinutes: null, qualificationScreeningMinutes: null, preparationMinutes: null, startLatencyMinutes: null, payoutMethod: null, payoutDelay: null, providerFees: null, repeatability: Object.freeze({ oneOffStudy: true }), supplyAvailabilityState: 'PUBLIC_RESEARCH_STUDY_AVAILABLE', supplyObservedAt: KOREAN_POCKET_MONEY_OBSERVED_AT, applicationRequired: true, qualificationRequired: true, qualificationProbability: null, acceptanceProbability: null, rejectionOrReversalRisk: null, payoutReliability: null, eligibleCountriesOrRegions: Object.freeze(['KOREA']), languageRequirements: null, skillRequirements: null, deviceOsRequirements: null, identityKycRequirements: null, ageRequirements: null, taxContractorRequirements: null, schedulingRequirements: null, canonicalDestinationUrl: url, createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
  const evidence = (suffix: string, fieldPath: string, text: string): OpportunityEvidence => { const locator = Object.freeze({ url, observationMode: 'OFFICIAL_PUBLIC_HOMEPAGE_CURRENT_RESEARCH_LIST' }); return Object.freeze({ id: `ev-w8-panelpower-airdresser-${suffix}`, offerVersionId: versionId, sourceSnapshotId: snapshotId, fieldPath, evidenceText: text, evidenceLocator: locator, evidenceHash: stableEvidenceHash({ fieldPath, text, locator }), confidence: 1, createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT }); };
  const evidenceRows = Object.freeze([evidence('study', 'title', 'Official PanelPower homepage currently lists a home-visit interview for purchasers of a 2026 Samsung AirDresser.'), evidence('reward', 'advertisedCompensationValue', 'Current public listing advertises KRW 300,000.'), evidence('requirement', 'qualificationRequired', 'The public study title targets purchasers of a 2026 model Samsung AirDresser.')]);
  const requirement: OpportunityRequirement = Object.freeze({ id: 'req-w8-panelpower-airdresser-purchaser', offerVersionId: versionId, requirementType: 'QUALIFICATION', operator: 'REQUIRED', normalizedValue: Object.freeze({ purchaserOf: '2026 Samsung AirDresser' }), displayText: 'Applicant must match the public purchaser target for a 2026 Samsung AirDresser.', required: true, confidence: 1, evidenceId: evidenceRows[2]!.id });
  const compensation: OpportunityCompensationComponent = Object.freeze({ id: 'comp-w8-panelpower-airdresser-fixed', offerVersionId: versionId, componentType: 'FIXED_PAY', amount: 300000, currency: 'KRW', rateUnit: null, percent: null, capAmount: null, conditionText: 'Advertised study compensation; payment remains conditional on study selection/participation requirements.', evidenceId: evidenceRows[1]!.id });
  const window: OpportunityWindow = Object.freeze({ id: 'window-w8-panelpower-airdresser-application', offerVersionId: versionId, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'WHILE_CURRENT_PUBLIC_RESEARCH_LISTING_REMAINS_OPEN', displayText: 'Current homepage listing is present; no exact public deadline is asserted.', evidenceId: evidenceRows[0]!.id });
  const queue: ReviewQueueItem = Object.freeze({ id: 'rq-w8-panelpower-airdresser-v1', offerVersionId: versionId, reasonCodes: Object.freeze(['REAL_CURRENT_SHORT_RESEARCH','TARGETED_PURCHASER_REQUIREMENT','FIXED_ADVERTISED_COMPENSATION']), priority: 'HIGH', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT, resolvedAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
  const review: ReviewDecisionRecord = Object.freeze({ id: 'review-w8-panelpower-airdresser-v1', reviewQueueId: queue.id, offerVersionId: versionId, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Official current PanelPower homepage supports the exact short paid-research title, KRW 300,000 advertised compensation and purchaser targeting. Duration, deadline, selection probability and guaranteed payment remain unasserted.', rejectionReason: null, patch: null, createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
  return Object.freeze({ slot: 20, realEvidence: true, syntheticFixture: false, sourcePolicy: KOREAN_POCKET_MONEY_POLICIES.PANELPOWER, sourceGates: GATES.PANELPOWER, snapshot, opportunity, version, certaintyType: 'CONDITIONAL', requirements: Object.freeze([requirement]), compensationComponents: Object.freeze([compensation]), windows: Object.freeze([window]), evidence: evidenceRows, reviewQueue: queue, reviewDecision: review, criticalEvidenceIds: Object.freeze(evidenceRows.map((x) => x.id)), lastCheckedAt: KOREAN_POCKET_MONEY_OBSERVED_AT, supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY' });
})();

export const KOREAN_POCKET_MONEY_VERIFIED20_RECORDS: readonly Verified20Record[] = Object.freeze([
  RAKUTEN_INSIGHT_KR_RECORD,
  PANELPOWER_PROGRAM_RECORD,
  IPSOS_ISAY_KR_RECORD,
  LIFEPOINTS_KR_RECORD,
  GOOGLE_OPINION_REWARDS_KR_RECORD,
  PANELPOWER_AIRDRESSER_RECORD,
]);
