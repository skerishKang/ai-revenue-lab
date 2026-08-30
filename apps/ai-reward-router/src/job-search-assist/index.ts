export const PRODUCT_OPPORTUNITY_LANES = {
  POCKET_MONEY: 'POCKET_MONEY',
  SHORT_GIG: 'SHORT_GIG',
  EXTERNAL_JOB_SEARCH: 'EXTERNAL_JOB_SEARCH',
} as const;

export type ProductOpportunityLane = (typeof PRODUCT_OPPORTUNITY_LANES)[keyof typeof PRODUCT_OPPORTUNITY_LANES];

export const PRODUCT_SCOPE_POLICY = Object.freeze({
  coreCatalogLanes: Object.freeze([
    PRODUCT_OPPORTUNITY_LANES.POCKET_MONEY,
    PRODUCT_OPPORTUNITY_LANES.SHORT_GIG,
  ]),
  externalOnlyLane: PRODUCT_OPPORTUNITY_LANES.EXTERNAL_JOB_SEARCH,
  generalJobListingsOwnedByB64: false,
  fullJobDescriptionReplication: false,
  applicationWorkflowOwnedByB64: false,
  hiringStatusSourceOfTruthOwnedByB64: false,
  externalJobSearchBehavior: 'AI_SEARCH_COMPARE_AND_DEEP_LINK',
  rationale: 'B64 owns discovery/routing for pocket money and short gigs. General part-time/job search is delegated to established job boards and official employer pages, with B64 AI helping users search, compare and navigate faster.',
});

export interface ExternalJobSearchReference {
  readonly sourceId: string;
  readonly provider: string;
  readonly title: string;
  readonly location: string;
  readonly workMode: 'REMOTE' | 'ONSITE' | 'HYBRID' | 'UNKNOWN';
  readonly compensationSummary: string | null;
  readonly destinationUrl: string;
  readonly lastCheckedAt: string;
  readonly lane: 'EXTERNAL_JOB_SEARCH';
  readonly applicationManagedExternally: true;
  readonly fullDescriptionStoredByB64: false;
}

const observedAt = '2026-08-30T09:01:42.000Z';

/**
 * Examples discovered during W8 research. These are intentionally NOT VERIFIED-20
 * catalog records. They are external search references only. B64 should refresh
 * or rediscover equivalent jobs at user-search time rather than operate a job DB.
 */
export const WELO_EXTERNAL_JOB_REFERENCES: readonly ExternalJobSearchReference[] = Object.freeze([
  Object.freeze({ sourceId: 'SRC-WELO', provider: 'Welo Global', title: 'Alpheratz — Korean Translation Quality Rater', location: 'South Korea', workMode: 'REMOTE', compensationSummary: 'Public posting observed at USD 30/hour.', destinationUrl: 'https://jobs.lever.co/weloglobal/0aa00a3e-df19-4b35-8873-eca10a8b7791', lastCheckedAt: observedAt, lane: 'EXTERNAL_JOB_SEARCH', applicationManagedExternally: true, fullDescriptionStoredByB64: false }),
  Object.freeze({ sourceId: 'SRC-WELO', provider: 'Welo Global', title: 'Alpheratz — Korean Translation Quality Reviewer', location: 'South Korea', workMode: 'REMOTE', compensationSummary: 'Public posting observed at USD 37.50/hour.', destinationUrl: 'https://jobs.lever.co/weloglobal/a73f4f10-c90d-4b33-b62e-0a6948f4dc5a', lastCheckedAt: observedAt, lane: 'EXTERNAL_JOB_SEARCH', applicationManagedExternally: true, fullDescriptionStoredByB64: false }),
  Object.freeze({ sourceId: 'SRC-WELO', provider: 'Welo Global', title: 'Circinus — Audio Contributor Korean', location: 'South Korea', workMode: 'REMOTE', compensationSummary: 'Public posting observed at USD 18/hour.', destinationUrl: 'https://jobs.lever.co/weloglobal/21bed87c-777f-4336-8d6a-eb120e09c2fd', lastCheckedAt: observedAt, lane: 'EXTERNAL_JOB_SEARCH', applicationManagedExternally: true, fullDescriptionStoredByB64: false }),
  Object.freeze({ sourceId: 'SRC-WELO', provider: 'Welo Global', title: 'Project Epsilon — Korean Data Trainer', location: 'South Korea', workMode: 'REMOTE', compensationSummary: 'Public posting observed at USD 42/hour.', destinationUrl: 'https://jobs.lever.co/weloglobal/62d41823-519a-43e9-afa4-765e194a2bd7', lastCheckedAt: observedAt, lane: 'EXTERNAL_JOB_SEARCH', applicationManagedExternally: true, fullDescriptionStoredByB64: false }),
  Object.freeze({ sourceId: 'SRC-WELO', provider: 'Welo Global', title: 'Project Epsilon — Korean Quality Control Specialist', location: 'South Korea', workMode: 'REMOTE', compensationSummary: 'Public posting observed at USD 46.20/hour.', destinationUrl: 'https://jobs.lever.co/weloglobal/06ad9ffd-d945-456d-b822-0d1a1bb488ed', lastCheckedAt: observedAt, lane: 'EXTERNAL_JOB_SEARCH', applicationManagedExternally: true, fullDescriptionStoredByB64: false }),
  Object.freeze({ sourceId: 'SRC-WELO', provider: 'Welo Global', title: 'Ara Zeta — AI Safety Evaluator Korean', location: 'South Korea', workMode: 'REMOTE', compensationSummary: 'Public posting observed at USD 22/hour.', destinationUrl: 'https://jobs.lever.co/weloglobal/494c384e-9ecc-4d0d-9e63-5b8a4257b66e', lastCheckedAt: observedAt, lane: 'EXTERNAL_JOB_SEARCH', applicationManagedExternally: true, fullDescriptionStoredByB64: false }),
]);

export interface JobSearchAssistQuery {
  readonly query: string;
  readonly location?: string | null;
  readonly desiredHours?: string | null;
  readonly remotePreference?: 'REMOTE' | 'ONSITE' | 'HYBRID' | 'ANY';
}

export function jobSearchAssistPrompt(input: JobSearchAssistQuery): string {
  const details = [
    input.query,
    input.location ? `location=${input.location}` : null,
    input.desiredHours ? `hours=${input.desiredHours}` : null,
    input.remotePreference ? `mode=${input.remotePreference}` : null,
  ].filter((value): value is string => value !== null);
  return `Search established job boards and official employer pages for ${details.join(', ')}. Compare only fresh public postings, summarize briefly, and deep-link the user to the source. Do not ingest or operate the job listing as B64-owned inventory.`;
}
