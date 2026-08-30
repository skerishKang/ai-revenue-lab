import {
  ACQUISITION_MODES,
  type Source,
  type SourceCollectionGate,
  type SourceEndpoint,
  type SourcePolicyReview,
} from './domain.js';

const source = (
  value: Omit<Source, 'opportunityClassHint'> & { opportunityClassHint: string | readonly string[] },
): Source => ({
  ...value,
  opportunityClassHint:
    typeof value.opportunityClassHint === 'string'
      ? value.opportunityClassHint.split('|')
      : [...value.opportunityClassHint],
});

/** Fresh 09 registry identities. This is metadata, not a live inventory. */
export const CURRENT_SOURCE_REGISTRY: readonly Source[] = [
  source({ sourceId: 'SRC-TOSS', sourceName: 'Toss Pay', sourceType: 'OFFICIAL_PUBLIC', lane: 'BUILD', launchPriority: 'P0', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: false, jsRendered: 'UNKNOWN', monetizationRole: 'TRAFFIC', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: null, listUrl: null, nextAction: 'Build first collector + manual policy review', notes: 'Public core source', acquisitionMode: ACQUISITION_MODES.MANUAL_CURATED_OFFICIAL_SOURCE, opportunityClassHint: 'PROMOTION' }),
  source({ sourceId: 'SRC-NPAY', sourceName: 'Naver Pay', sourceType: 'OFFICIAL_PUBLIC', lane: 'BUILD', launchPriority: 'P0', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: false, jsRendered: 'UNKNOWN', monetizationRole: 'TRAFFIC', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: null, listUrl: null, nextAction: 'Build second collector + manual policy review', notes: 'Public core source', acquisitionMode: ACQUISITION_MODES.MANUAL_CURATED_OFFICIAL_SOURCE, opportunityClassHint: 'PROMOTION' }),
  source({ sourceId: 'SRC-TMEM', sourceName: 'T Membership', sourceType: 'OFFICIAL_PUBLIC', lane: 'BUILD', launchPriority: 'P0', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: false, jsRendered: 'UNKNOWN', monetizationRole: 'TRAFFIC', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: null, listUrl: null, nextAction: 'Build third collector + manual policy review', notes: 'Public core source', acquisitionMode: ACQUISITION_MODES.MANUAL_CURATED_OFFICIAL_SOURCE, opportunityClassHint: 'PROMOTION' }),
  source({ sourceId: 'SRC-CJONE', sourceName: 'CJ ONE', sourceType: 'OFFICIAL_PUBLIC', lane: 'BUILD', launchPriority: 'P0', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: false, jsRendered: 'UNKNOWN', monetizationRole: 'TRAFFIC', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: null, listUrl: null, nextAction: 'Build fourth collector + manual policy review', notes: 'Public core source', acquisitionMode: ACQUISITION_MODES.MANUAL_CURATED_OFFICIAL_SOURCE, opportunityClassHint: 'PROMOTION' }),
  source({ sourceId: 'SRC-KB', sourceName: 'KB Kookmin Bank', sourceType: 'FINANCIAL', lane: 'SHADOW_ONLY', launchPriority: 'P1', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: false, jsRendered: 'UNKNOWN', monetizationRole: 'TRAFFIC', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'HIGH', updateCadence: 'DAILY', officialBaseUrl: null, listUrl: null, nextAction: 'Shadow ingestion only; human approval mandatory', notes: 'Financial/high-value', acquisitionMode: ACQUISITION_MODES.SHADOW_ONLY, opportunityClassHint: 'PROMOTION' }),
  source({ sourceId: 'SRC-SHINHAN', sourceName: 'Shinhan Card', sourceType: 'FINANCIAL', lane: 'SHADOW_ONLY', launchPriority: 'P1', country: 'KR', accessMode: 'PUBLIC_WEB', loginRequired: false, jsRendered: 'UNKNOWN', monetizationRole: 'TRAFFIC', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'HIGH', updateCadence: 'DAILY', officialBaseUrl: null, listUrl: null, nextAction: 'Shadow ingestion only; human approval mandatory', notes: 'Financial/high-value', acquisitionMode: ACQUISITION_MODES.SHADOW_ONLY, opportunityClassHint: 'PROMOTION' }),
  source({ sourceId: 'SRC-LINKPRICE', sourceName: 'LinkPrice', sourceType: 'AFFILIATE', lane: 'NEGOTIATE', launchPriority: 'P1', country: 'KR', accessMode: 'PARTNER', loginRequired: true, jsRendered: 'UNKNOWN', monetizationRole: 'REVENUE', verificationState: 'PARTNERSHIP_REQUIRED', riskTier: 'MEDIUM', updateCadence: 'PARTNER_FEED', officialBaseUrl: null, listUrl: null, nextAction: 'Validate incentive policy, Sub ID, postback, test conversion', notes: 'Domestic revenue track', acquisitionMode: ACQUISITION_MODES.PARTNER_FEED, opportunityClassHint: 'AFFILIATE_ACTION' }),
  source({ sourceId: 'SRC-AYET', sourceName: 'ayeT-Studios', sourceType: 'OFFERWALL', lane: 'INVENTORY_TEST', launchPriority: 'P2', country: 'GLOBAL', accessMode: 'PARTNER', loginRequired: true, jsRendered: 'UNKNOWN', monetizationRole: 'REVENUE', verificationState: 'PARTNERSHIP_REQUIRED', riskTier: 'MEDIUM', updateCadence: 'PARTNER_FEED', officialBaseUrl: 'https://www.ayetstudios.com/', listUrl: 'https://www.ayetstudios.com/openapi/publisher-doc', nextAction: 'Obtain publisher account/adslot/API credentials; test KR web/desktop offer + survey inventory; verify incentive, settlement, and callback rules', notes: 'Official publisher API supports Offerwall API, Surveywall API, desktop/web targeting and conversion callbacks; publisher setup required', acquisitionMode: ACQUISITION_MODES.PARTNER_API, opportunityClassHint: 'OFFERWALL|SURVEY' }),
  source({ sourceId: 'SRC-ADISON', sourceName: 'AdiSON', sourceType: 'OFFERWALL', lane: 'NEGOTIATE', launchPriority: 'P0', country: 'KR', accessMode: 'PARTNER_API', loginRequired: true, jsRendered: 'UNKNOWN', monetizationRole: 'REVENUE', verificationState: 'PARTNERSHIP_REQUIRED', riskTier: 'MEDIUM', updateCadence: 'PARTNER_FEED', officialBaseUrl: 'https://adison.co/', listUrl: 'https://adison.co/monetization/', nextAction: 'Publisher onboarding + Web/API commercial terms + live inventory test', notes: 'Domestic revenue core; official offerwall partner material reviewed', acquisitionMode: ACQUISITION_MODES.PARTNER_API, opportunityClassHint: 'OFFERWALL' }),
  source({ sourceId: 'SRC-TNK', sourceName: 'TNK Factory', sourceType: 'OFFERWALL', lane: 'NEGOTIATE', launchPriority: 'P0', country: 'KR', accessMode: 'PARTNER_SDK_API', loginRequired: true, jsRendered: 'UNKNOWN', monetizationRole: 'REVENUE', verificationState: 'PARTNERSHIP_REQUIRED', riskTier: 'MEDIUM', updateCadence: 'PARTNER_FEED', officialBaseUrl: 'https://www.tnkfactory.com/', listUrl: 'https://www.tnkfactory.com/tnk/ko/tnk.home.main?action=developer', nextAction: 'Publisher onboarding + KakaoPay/reward product terms + web feasibility', notes: 'Domestic revenue core; publisher material is not a B64 permission grant', acquisitionMode: ACQUISITION_MODES.PARTNER_WIDGET_SDK, opportunityClassHint: 'OFFERWALL|REWARDED_AD' }),
  source({ sourceId: 'SRC-ADPOPCORN', sourceName: 'AdPopcorn', sourceType: 'OFFERWALL', lane: 'NEGOTIATE', launchPriority: 'P1', country: 'KR', accessMode: 'PARTNER_SDK', loginRequired: true, jsRendered: 'UNKNOWN', monetizationRole: 'REVENUE', verificationState: 'PARTNERSHIP_REQUIRED', riskTier: 'MEDIUM', updateCadence: 'PARTNER_FEED', officialBaseUrl: 'https://www.adpopcorn.com/', listUrl: 'https://reward.adpopcorn.com/', nextAction: 'Confirm publisher onboarding, web/PWA path, and reward settlement', notes: 'Domestic reward-ad candidate', acquisitionMode: ACQUISITION_MODES.PARTNER_WIDGET_SDK, opportunityClassHint: 'OFFERWALL|REWARDED_AD' }),
  source({ sourceId: 'SRC-CPX', sourceName: 'CPX Research', sourceType: 'SURVEYWALL', lane: 'INVENTORY_TEST', launchPriority: 'P0', country: 'GLOBAL', accessMode: 'WEB_API', loginRequired: true, jsRendered: true, monetizationRole: 'REVENUE', verificationState: 'PARTNERSHIP_REQUIRED', riskTier: 'MEDIUM', updateCadence: 'LIVE_FEED', officialBaseUrl: 'https://www.cpx-research.com/', listUrl: 'https://cpx-research.com/main/en/doc.php', nextAction: 'Obtain publisher account/app credentials; test KR live survey inventory through web API and payout mapping', notes: 'Official docs confirm web API options; publisher setup required', acquisitionMode: ACQUISITION_MODES.PARTNER_API, opportunityClassHint: 'SURVEY' }),
  source({ sourceId: 'SRC-PROLIFIC', sourceName: 'Prolific', sourceType: 'GLOBAL_WORK', lane: 'BUILD', launchPriority: 'P1', country: 'GLOBAL/KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: 'UNKNOWN', monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'LOW', updateCadence: 'WEEKLY', officialBaseUrl: 'https://www.prolific.com/', listUrl: 'https://participant-help.prolific.com/en/articles/445007-who-can-participate-in-studies-on-prolific', nextAction: 'Track Korea participant availability/waitlist and study freshness; do not assume a participant opportunity feed', notes: 'PIPELINE value-only; curated/deep-link only until permitted integration exists', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'MARKET_RESEARCH' }),
  source({ sourceId: 'SRC-OUTLIER', sourceName: 'Outlier', sourceType: 'GLOBAL_AI_WORK', lane: 'BUILD', launchPriority: 'P1', country: 'GLOBAL/KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: true, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: 'https://outlier.ai/', listUrl: 'https://outlier.ai/languages/ko-kr', nextAction: 'Track Korean AI role availability and application/qualification status', notes: 'PIPELINE value-only; application/qualification required', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'AI_EVALUATION' }),
  source({ sourceId: 'SRC-CROWDGEN', sourceName: 'CrowdGen by Appen', sourceType: 'GLOBAL_AI_WORK', lane: 'BUILD', launchPriority: 'P1', country: 'GLOBAL/KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: true, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'WEEKLY', officialBaseUrl: 'https://crowdgen.com/', listUrl: 'https://crowdgen.com/remote-work/', nextAction: 'Track Korea-eligible AI/data projects, qualification gates and payout availability; do not assume a public work feed', notes: 'PIPELINE value-only; qualifications required; no B64 income guarantee', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'AI_EVALUATION|DATA_ANNOTATION' }),
  source({ sourceId: 'SRC-TELUS', sourceName: 'TELUS Digital AI Community', sourceType: 'GLOBAL_AI_WORK', lane: 'BUILD', launchPriority: 'P1', country: 'GLOBAL/KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: true, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: 'https://jobs.telusdigital.com/', listUrl: 'https://jobs.telusdigital.com/search/jobs/in/country/korea-republic-of', nextAction: 'Track current South Korea remote part-time AI/community jobs', notes: 'PIPELINE value-only; application/assessment required', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'SEARCH_OR_QUALITY_EVALUATION' }),
  source({ sourceId: 'SRC-ONEFORMA', sourceName: 'OneForma', sourceType: 'GLOBAL_AI_WORK', lane: 'BUILD', launchPriority: 'P1', country: 'GLOBAL/KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: true, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: 'https://www.oneforma.com/', listUrl: 'https://www.oneforma.com/jobs/', nextAction: 'Track Korea projects, certification gates, and payout options', notes: 'PIPELINE value-only; certification gates required', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'SEARCH_OR_QUALITY_EVALUATION|DATA_ANNOTATION' }),
  source({ sourceId: 'SRC-CLICKWORKER', sourceName: 'Clickworker', sourceType: 'GLOBAL_MICROTASK', lane: 'BUILD', launchPriority: 'P2', country: 'GLOBAL', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: true, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: 'https://www.clickworker.com/', listUrl: 'https://www.clickworker.com/clickworker/', nextAction: 'Verify Korea registration, workload and payment-method availability before promotion; do not assume a public job feed', notes: 'PIPELINE value-only; country registration/workload is dynamic', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'MICROTASK' }),
  source({ sourceId: 'SRC-UTEST', sourceName: 'uTest', sourceType: 'GLOBAL_TESTING', lane: 'BUILD', launchPriority: 'P2', country: 'GLOBAL/KR', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: true, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'DAILY', officialBaseUrl: 'https://www.utest.com/', listUrl: 'https://www.utest.com/projects', nextAction: 'Track Korea-included testing projects and application status', notes: 'PIPELINE value-only; global software-testing project board', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'USER_TESTING' }),
  source({ sourceId: 'SRC-USERTESTING', sourceName: 'UserTesting', sourceType: 'GLOBAL_TESTING', lane: 'BUILD', launchPriority: 'P2', country: 'GLOBAL', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: true, monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'WEEKLY', officialBaseUrl: 'https://www.usertesting.com/', listUrl: 'https://support.usertesting.com/', nextAction: 'Verify current Korea sign-up eligibility at runtime; do not assume a participant opportunity feed', notes: 'PIPELINE value-only; country eligibility changes with supply/demand', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'USER_TESTING' }),
  source({ sourceId: 'SRC-RESPONDENT', sourceName: 'Respondent', sourceType: 'GLOBAL_RESEARCH', lane: 'BUILD', launchPriority: 'P2', country: 'GLOBAL', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: 'UNKNOWN', monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'WEEKLY', officialBaseUrl: 'https://www.respondent.io/', listUrl: 'https://help.respondent.io/en/articles/5456426-how-respondent-works-and-how-to-earn-money', nextAction: 'Verify Korea/remote project availability and any permitted partner/feed path; model unpaid screener and selection probability', notes: 'PIPELINE candidate; no B64 feed assumed', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'MARKET_RESEARCH' }),
  source({ sourceId: 'SRC-TOLOKA', sourceName: 'Toloka', sourceType: 'GLOBAL_MICROTASK', lane: 'HOLD', launchPriority: 'P2', country: 'GLOBAL', accessMode: 'PUBLIC_WEB', loginRequired: true, jsRendered: 'UNKNOWN', monetizationRole: 'NONE', verificationState: 'RESEARCH_SUPPORTED', riskTier: 'MEDIUM', updateCadence: 'WEEKLY', officialBaseUrl: 'https://toloka.ai/', listUrl: 'https://toloka.ai/get-started', nextAction: 'Verify current Korea eligibility, payout methods and task availability before moving from HOLD; model acceptance/rejection risk', notes: 'PIPELINE candidate; current Korea/payment availability not yet verified', acquisitionMode: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, opportunityClassHint: 'MICROTASK|DATA_ANNOTATION' }),
];

export const CURRENT_SOURCE_IDS = Object.freeze(CURRENT_SOURCE_REGISTRY.map(({ sourceId }) => sourceId));

export const CURRENT_SOURCE_ENDPOINTS: readonly SourceEndpoint[] = [
  { endpointId: 'EP-TOSS-LIST', sourceId: 'SRC-TOSS', endpointKind: 'LIST', url: null, requiresAuth: 'UNKNOWN', renderMode: 'TBD', intendedBehavior: 'Offer/event listing', enabled: true, evidenceNotes: 'Populate after live verification' },
  { endpointId: 'EP-NPAY-LIST', sourceId: 'SRC-NPAY', endpointKind: 'LIST', url: null, requiresAuth: 'UNKNOWN', renderMode: 'TBD', intendedBehavior: 'Offer/event listing', enabled: true, evidenceNotes: 'Populate after live verification' },
  { endpointId: 'EP-TMEM-LIST', sourceId: 'SRC-TMEM', endpointKind: 'LIST', url: null, requiresAuth: 'UNKNOWN', renderMode: 'TBD', intendedBehavior: 'Membership benefit listing', enabled: true, evidenceNotes: 'Populate after live verification' },
  { endpointId: 'EP-CJONE-LIST', sourceId: 'SRC-CJONE', endpointKind: 'LIST', url: null, requiresAuth: 'UNKNOWN', renderMode: 'TBD', intendedBehavior: 'Benefit/event listing', enabled: true, evidenceNotes: 'Populate after live verification' },
];

const policyFor = (sourceId: string): SourcePolicyReview => ({
  sourceId,
  robotsStatus: 'NOT_CHECKED',
  termsStatus: 'NOT_CHECKED',
  commercialReuse: 'UNKNOWN',
  textReuse: 'UNKNOWN',
  imageLogoReuse: 'UNKNOWN',
  automationPermission: 'UNKNOWN',
  affiliateIncentive: 'UNKNOWN',
  policyEvidenceUrl: null,
  reviewedAt: null,
  reviewer: null,
  decision: 'PENDING',
  notes: null,
});

export const CURRENT_SOURCE_POLICY_REVIEWS: readonly SourcePolicyReview[] = Object.freeze(
  CURRENT_SOURCE_IDS.map(policyFor),
);

const gateNames = [
  ['Source identity verified', 'BLOCK'],
  ['Official endpoint identified', 'BLOCK'],
  ['robots reviewed', 'BLOCK'],
  ['terms/commercial reuse reviewed', 'BLOCK'],
  ['collector stability test', 'SHADOW'],
  ['evidence extraction works', 'SHADOW'],
  ['change detection works', 'SHADOW'],
  ['human review accepted sample', 'SHADOW'],
] as const;

export const CURRENT_SOURCE_COLLECTION_GATES: readonly SourceCollectionGate[] = Object.freeze(
  CURRENT_SOURCE_IDS.flatMap((sourceId) =>
    gateNames.map(([gate, failureAction], index) => ({
      gateId: `${sourceId}-G${index + 1}`,
      sourceId,
      gate,
      required: true,
      status: 'NOT_STARTED' as const,
      failureAction,
      evidence: null,
      notes: null,
    })),
  ),
);

export function sourceById(sourceId: string): Source {
  const found = CURRENT_SOURCE_REGISTRY.find((item) => item.sourceId === sourceId);
  if (!found) throw new Error(`Unknown B64 source: ${sourceId}`);
  return found;
}

export function policyBySourceId(sourceId: string): SourcePolicyReview {
  const found = CURRENT_SOURCE_POLICY_REVIEWS.find((item) => item.sourceId === sourceId);
  if (!found) throw new Error(`Missing policy review: ${sourceId}`);
  return found;
}

export function gatesBySourceId(sourceId: string): readonly SourceCollectionGate[] {
  return CURRENT_SOURCE_COLLECTION_GATES.filter((item) => item.sourceId === sourceId);
}
