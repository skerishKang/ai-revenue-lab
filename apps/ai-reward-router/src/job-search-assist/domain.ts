export const P4_SOURCE_AUTHORITIES = [
  'OFFICIAL_EMPLOYER',
  'ESTABLISHED_JOB_BOARD',
  'OTHER_PUBLIC_SOURCE',
  'UNKNOWN',
] as const;
export type P4SourceAuthority = (typeof P4_SOURCE_AUTHORITIES)[number];

export const P4_POSTING_AVAILABILITY = [
  'PUBLIC_POSTING_OBSERVED',
  'PUBLIC_POSTING_ENDED',
  'UNKNOWN',
] as const;
export type P4PostingAvailability = (typeof P4_POSTING_AVAILABILITY)[number];

export const P4_RESULT_STATES = [
  'REFERENCE_READY',
  'REFRESH_REQUIRED',
  'BLOCKED_ENDED',
  'BLOCKED_UNSAFE_DESTINATION',
  'BLOCKED_SOURCE_AUTHORITY',
  'BLOCKED_OWNERSHIP_BOUNDARY',
  'BLOCKED_INVALID_DATA',
] as const;
export type P4ResultState = (typeof P4_RESULT_STATES)[number];

export type P4WorkMode = 'REMOTE' | 'ONSITE' | 'HYBRID' | 'UNKNOWN';
export type P4CompensationUnit = 'HOUR' | 'DAY' | 'MONTH' | 'YEAR' | 'TASK' | 'PROJECT';

export interface P4ObservedCompensation {
  readonly amount: number;
  readonly currency: string;
  readonly unit: P4CompensationUnit;
  readonly explicitlyObserved: true;
}

export interface P4ExternalJobCandidate {
  readonly sourceId: string;
  readonly provider: string;
  readonly title: string;
  readonly location: string;
  readonly workMode: P4WorkMode;
  readonly compensationSummary: string | null;
  readonly observedCompensation: P4ObservedCompensation | null;
  readonly destinationUrl: string;
  readonly lastCheckedAt: string;
  readonly sourceAuthority: P4SourceAuthority;
  readonly postingAvailability: P4PostingAvailability;
  readonly applicationManagedExternally: boolean;
  readonly fullDescriptionStoredByB64: boolean;
  readonly b64OwnedInventory: boolean;
}

export interface P4PreparedReference {
  readonly canonicalKey: string;
  readonly sourceId: string;
  readonly provider: string;
  readonly title: string;
  readonly location: string;
  readonly workMode: P4WorkMode;
  readonly compensationSummary: string | null;
  readonly normalizedCompensation: P4ObservedCompensation | null;
  readonly compensationKnown: boolean;
  readonly destinationUrl: string;
  readonly lastCheckedAt: string;
  readonly sourceAuthority: P4SourceAuthority;
  readonly postingAvailability: P4PostingAvailability;
  readonly resultState: P4ResultState;
  readonly hiringStatus: 'UNKNOWN';
  readonly sourceOfTruth: 'EXTERNAL_PROVIDER';
  readonly applicationManagedExternally: true;
  readonly fullDescriptionStoredByB64: false;
  readonly b64OwnedInventory: false;
  readonly lane: 'EXTERNAL_JOB_SEARCH';
  readonly unresolvedFields: readonly string[];
}

export interface P4ComparisonPreferences {
  readonly location?: string | null;
  readonly remotePreference?: 'REMOTE' | 'ONSITE' | 'HYBRID' | 'ANY';
  readonly preferredCurrency?: string | null;
}

export const P4_VISIBILITY_LOCK = Object.freeze({
  issueNumber: 1138 as const,
  consumerVisible: false as const,
  primaryNavigationVisible: false as const,
  homeSectionVisible: false as const,
  todayRouteVisible: false as const,
  automaticUnlockAllowed: false as const,
  unlockAuthority: 'SEPARATE_OWNER_CENTRAL_DECISION_AFTER_P0_P1_P2_P3_SEQUENCE' as const,
});

export const P4_PRODUCT_BOUNDARY = Object.freeze({
  generalJobListingsOwnedByB64: false as const,
  fullJobDescriptionReplicationAllowed: false as const,
  applicationWorkflowOwnedByB64: false as const,
  hiringStatusSourceOfTruthOwnedByB64: false as const,
  boundedSearchReferenceRetentionAllowed: true as const,
  searchBehavior: 'AI_SEARCH_COMPARE_RANK_AND_DEEP_LINK' as const,
  sourceOfTruth: 'EXTERNAL_JOB_BOARD_OR_OFFICIAL_EMPLOYER' as const,
});

export const P4_DEFAULT_FRESHNESS_HOURS = 168 as const;

const TRUSTED_SOURCE_AUTHORITIES = new Set<P4SourceAuthority>([
  'OFFICIAL_EMPLOYER',
  'ESTABLISHED_JOB_BOARD',
]);

function canonicalDestination(urlText: string): string | null {
  try {
    const url = new URL(urlText);
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) return null;
    const hostname = url.hostname.toLowerCase();
    if (hostname === 'localhost' || hostname.endsWith('.local')) return null;
    url.hash = '';
    url.searchParams.sort();
    return url.toString();
  } catch {
    return null;
  }
}

function canonicalKeyFor(candidate: P4ExternalJobCandidate): string {
  const destination = canonicalDestination(candidate.destinationUrl) ?? candidate.destinationUrl.trim();
  return `${candidate.sourceId.trim().toUpperCase()}:${destination}`;
}

function validObservedCompensation(value: P4ObservedCompensation | null): P4ObservedCompensation | null {
  if (value === null) return null;
  if (value.explicitlyObserved !== true) return null;
  if (!Number.isFinite(value.amount) || value.amount <= 0) return null;
  const currency = value.currency.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(currency)) return null;
  return Object.freeze({ ...value, currency });
}

function ageHours(lastCheckedAt: string, nowIso: string): number | null {
  const checked = Date.parse(lastCheckedAt);
  const now = Date.parse(nowIso);
  if (!Number.isFinite(checked) || !Number.isFinite(now) || checked > now) return null;
  return (now - checked) / 3_600_000;
}

function unresolvedFields(candidate: P4ExternalJobCandidate): readonly string[] {
  const fields: string[] = [];
  if (!candidate.location.trim()) fields.push('location');
  if (candidate.workMode === 'UNKNOWN') fields.push('workMode');
  if (candidate.observedCompensation === null) fields.push('compensation');
  if (candidate.postingAvailability === 'UNKNOWN') fields.push('postingAvailability');
  return Object.freeze(fields);
}

function resultStateFor(
  candidate: P4ExternalJobCandidate,
  nowIso: string,
  freshnessHours: number,
): P4ResultState {
  if (!candidate.sourceId.trim() || !candidate.provider.trim() || !candidate.title.trim()) return 'BLOCKED_INVALID_DATA';
  if (canonicalDestination(candidate.destinationUrl) === null) return 'BLOCKED_UNSAFE_DESTINATION';
  if (!TRUSTED_SOURCE_AUTHORITIES.has(candidate.sourceAuthority)) return 'BLOCKED_SOURCE_AUTHORITY';
  if (candidate.b64OwnedInventory || candidate.fullDescriptionStoredByB64 || !candidate.applicationManagedExternally) {
    return 'BLOCKED_OWNERSHIP_BOUNDARY';
  }
  if (candidate.postingAvailability === 'PUBLIC_POSTING_ENDED') return 'BLOCKED_ENDED';
  const age = ageHours(candidate.lastCheckedAt, nowIso);
  if (age === null) return 'BLOCKED_INVALID_DATA';
  if (age > freshnessHours || candidate.postingAvailability === 'UNKNOWN') return 'REFRESH_REQUIRED';
  return 'REFERENCE_READY';
}

export function prepareP4ExternalJobReference(
  candidate: P4ExternalJobCandidate,
  nowIso: string,
  freshnessHours = P4_DEFAULT_FRESHNESS_HOURS,
): P4PreparedReference {
  const normalizedUrl = canonicalDestination(candidate.destinationUrl) ?? candidate.destinationUrl.trim();
  const compensation = validObservedCompensation(candidate.observedCompensation);
  return Object.freeze({
    canonicalKey: canonicalKeyFor(candidate),
    sourceId: candidate.sourceId,
    provider: candidate.provider,
    title: candidate.title,
    location: candidate.location,
    workMode: candidate.workMode,
    compensationSummary: candidate.compensationSummary,
    normalizedCompensation: compensation,
    compensationKnown: compensation !== null,
    destinationUrl: normalizedUrl,
    lastCheckedAt: candidate.lastCheckedAt,
    sourceAuthority: candidate.sourceAuthority,
    postingAvailability: candidate.postingAvailability,
    resultState: resultStateFor(candidate, nowIso, freshnessHours),
    hiringStatus: 'UNKNOWN',
    sourceOfTruth: 'EXTERNAL_PROVIDER',
    applicationManagedExternally: true,
    fullDescriptionStoredByB64: false,
    b64OwnedInventory: false,
    lane: 'EXTERNAL_JOB_SEARCH',
    unresolvedFields: unresolvedFields(candidate),
  });
}

function preferencePenalty(item: P4PreparedReference, preferences: P4ComparisonPreferences): number {
  let penalty = 0;
  const desiredMode = preferences.remotePreference;
  if (desiredMode && desiredMode !== 'ANY' && item.workMode !== desiredMode) penalty += 2;
  if (preferences.location?.trim()) {
    const desired = preferences.location.trim().toLocaleLowerCase();
    if (!item.location.toLocaleLowerCase().includes(desired)) penalty += 1;
  }
  return penalty;
}

function comparableCompensation(
  left: P4ObservedCompensation | null,
  right: P4ObservedCompensation | null,
  preferredCurrency?: string | null,
): number {
  if (left === null || right === null) return 0;
  if (left.currency !== right.currency || left.unit !== right.unit) return 0;
  if (preferredCurrency && left.currency !== preferredCurrency.trim().toUpperCase()) return 0;
  return right.amount - left.amount;
}

export function compareP4ExternalJobReferences(
  left: P4PreparedReference,
  right: P4PreparedReference,
  preferences: P4ComparisonPreferences = {},
): number {
  const stateRank = (state: P4ResultState): number => state === 'REFERENCE_READY' ? 0 : state === 'REFRESH_REQUIRED' ? 1 : 2;
  const stateDifference = stateRank(left.resultState) - stateRank(right.resultState);
  if (stateDifference !== 0) return stateDifference;

  const preferenceDifference = preferencePenalty(left, preferences) - preferencePenalty(right, preferences);
  if (preferenceDifference !== 0) return preferenceDifference;

  const compensationDifference = comparableCompensation(
    left.normalizedCompensation,
    right.normalizedCompensation,
    preferences.preferredCurrency,
  );
  if (compensationDifference !== 0) return compensationDifference;

  const freshnessDifference = Date.parse(right.lastCheckedAt) - Date.parse(left.lastCheckedAt);
  if (Number.isFinite(freshnessDifference) && freshnessDifference !== 0) return freshnessDifference;
  return left.title.localeCompare(right.title);
}

export function buildP4HiddenSearchBacklog(
  candidates: readonly P4ExternalJobCandidate[],
  nowIso: string,
  preferences: P4ComparisonPreferences = {},
  freshnessHours = P4_DEFAULT_FRESHNESS_HOURS,
) {
  const prepared = candidates.map((candidate) => prepareP4ExternalJobReference(candidate, nowIso, freshnessHours));
  const seen = new Set<string>();
  const deduplicated: P4PreparedReference[] = [];
  let duplicateSuppressedCount = 0;

  for (const item of prepared) {
    if (seen.has(item.canonicalKey)) {
      duplicateSuppressedCount += 1;
      continue;
    }
    seen.add(item.canonicalKey);
    deduplicated.push(item);
  }

  deduplicated.sort((left, right) => compareP4ExternalJobReferences(left, right, preferences));
  const ready = deduplicated.filter((item) => item.resultState === 'REFERENCE_READY');

  return Object.freeze({
    mode: 'P4_EXTERNAL_JOB_SEARCH_PREPARATION_HIDDEN' as const,
    issueNumber: P4_VISIBILITY_LOCK.issueNumber,
    consumerVisible: P4_VISIBILITY_LOCK.consumerVisible,
    visibilityLock: P4_VISIBILITY_LOCK,
    productBoundary: P4_PRODUCT_BOUNDARY,
    preparedReferences: Object.freeze(deduplicated),
    readyReferences: Object.freeze(ready),
    readyCount: ready.length,
    suppressedCount: deduplicated.length - ready.length,
    duplicateSuppressedCount,
    sourceOfTruth: 'EXTERNAL_PROVIDER' as const,
    generalJobInventoryOwnedByB64: false as const,
  });
}
