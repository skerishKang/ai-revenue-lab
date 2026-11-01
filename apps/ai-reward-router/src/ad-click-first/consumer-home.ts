import {
  buildDefaultAdClickCards,
  type AdClickConsumerCandidate,
  type AdClickConsumerCard,
} from './consumer-card.js';
import {
  displayablePublicOpportunityCards,
  isPublicOpportunityDisplayable,
  toPublicOpportunityDetail,
  type PublicOpportunity,
  type PublicOpportunityCard,
  type PublicOpportunityDetail,
} from '../public-supply/domain.js';

export type ConsumerPrimaryNavId = 'EARN_NOW';
export type ConsumerSectionId = 'AVAILABLE_NOW';
export type AdClickFirstConsumerEmptyState = 'NO_LIVE_REWARD_SUPPLY';

export interface ConsumerPrimaryNavItem {
  readonly id: ConsumerPrimaryNavId;
  readonly label: string;
}

export interface AdClickFirstConsumerSection {
  readonly id: ConsumerSectionId;
  readonly title: string;
  readonly cards: readonly AdClickConsumerCard[];
}

export interface AdClickFirstConsumerHomeViewModel {
  readonly mode: 'AD_CLICK_FIRST';
  readonly issueNumber: 1112;
  readonly primaryNavigation: readonly ConsumerPrimaryNavItem[];
  readonly hero: Readonly<{
    eyebrow: string;
    title: string;
    description: string;
  }>;
  readonly sections: readonly AdClickFirstConsumerSection[];
  /**
   * Verified public opportunities (issue #5830): shown FIRST on the home
   * screen when present, because they are the only earning opportunities a
   * visitor can actually start today. Empty while no verified supply exists.
   */
  readonly publicCards: readonly PublicOpportunityCard[];
  readonly emptyState: AdClickFirstConsumerEmptyState | null;
  readonly accountOnboardingVisibleToConsumer: false;
  readonly laterTierNavigationVisible: false;
  readonly laterTierSectionsVisible: false;
}

export interface AdClickFirstTodayRouteViewModel {
  readonly mode: 'TODAY_ROUTE_AD_CLICK_FIRST';
  readonly cards: readonly AdClickConsumerCard[];
  readonly emptyState: AdClickFirstConsumerEmptyState | null;
  readonly laterTierSuggestionsVisible: false;
  readonly publicImmediateCards: readonly PublicOpportunityCard[];
  readonly publicScreeningCards: readonly PublicOpportunityCard[];
}

export type ConsumerBrowseCategory = 'ALL' | 'AD_CLICK' | 'SURVEY' | 'USABILITY' | 'MICROTASK' | 'SHORT_GIG';

export interface ConsumerBrowseCategoryItem {
  readonly id: ConsumerBrowseCategory;
  readonly label: string;
  readonly active: boolean;
  readonly count: number;
}

export interface AdClickFirstBrowseFilterState {
  readonly query: string;
  readonly maxSeconds: number | null;
  readonly category: ConsumerBrowseCategory;
}

export interface AdClickFirstBrowseViewModel {
  readonly mode: 'OPPORTUNITY_BROWSE_AD_CLICK_FIRST';
  readonly primaryNavigation: readonly ConsumerPrimaryNavItem[];
  readonly selectedCategory: ConsumerBrowseCategory;
  readonly categories: readonly ConsumerBrowseCategoryItem[];
  readonly cards: readonly AdClickConsumerCard[];
  readonly publicCards: readonly PublicOpportunityCard[];
  readonly filters: AdClickFirstBrowseFilterState;
  readonly emptyState: AdClickFirstConsumerEmptyState | null;
  readonly laterTierNotice: string;
  readonly publicSupplyNote: string | null;
  readonly accountOnboardingVisibleToConsumer: false;
  readonly laterTierNavigationVisible: false;
}

export interface AdClickFirstOpportunityDetailViewModel {
  readonly mode: 'OPPORTUNITY_DETAIL_AD_CLICK_FIRST';
  readonly primaryNavigation: readonly ConsumerPrimaryNavItem[];
  readonly card: AdClickConsumerCard | null;
  readonly publicDetail: PublicOpportunityDetail | null;
  readonly found: boolean;
  readonly emptyState: AdClickFirstConsumerEmptyState | null;
  readonly accountOnboardingVisibleToConsumer: false;
  readonly laterTierNavigationVisible: false;
}

const PRIMARY_NAVIGATION: readonly ConsumerPrimaryNavItem[] = Object.freeze([
  Object.freeze({ id: 'EARN_NOW' as const, label: '바로 적립' }),
]);

function byLowestActiveTime(a: AdClickConsumerCard, b: AdClickConsumerCard): number {
  return a.estimatedActiveSeconds - b.estimatedActiveSeconds;
}

/**
 * Consumer P0 presentation contract.
 *
 * The function accepts raw AD_CLICK candidates, applies the fail-closed card
 * eligibility contract, and exposes only cards that are already safe to show.
 * Later earning tiers and owner/operator account onboarding never enter this
 * consumer view-model.
 */
export interface BuildAdClickFirstConsumerHomeOptions {
  readonly publicOpportunities?: readonly PublicOpportunity[];
}

export function buildAdClickFirstConsumerHome(
  candidates: readonly AdClickConsumerCandidate[],
  options: BuildAdClickFirstConsumerHomeOptions = {},
): AdClickFirstConsumerHomeViewModel {
  const cards = Object.freeze([...buildDefaultAdClickCards(candidates)].sort(byLowestActiveTime));
  const publicCards = displayablePublicOpportunityCards(options.publicOpportunities ?? []);
  return Object.freeze({
    mode: 'AD_CLICK_FIRST' as const,
    issueNumber: 1112 as const,
    primaryNavigation: PRIMARY_NAVIGATION,
    hero: Object.freeze({
      eyebrow: 'B64 AI Reward Router',
      title: '오늘의 추천 수익 기회',
      description: '공개된 수익 기회와 확인된 참여 조건을 살펴보세요.',
    }),
    sections: Object.freeze([
      Object.freeze({
        id: 'AVAILABLE_NOW' as const,
        title: '바로 가능한 적립',
        cards,
      }),
    ]),
    publicCards,
    emptyState: cards.length === 0 && publicCards.length === 0 ? 'NO_LIVE_REWARD_SUPPLY' as const : null,
    accountOnboardingVisibleToConsumer: false as const,
    laterTierNavigationVisible: false as const,
    laterTierSectionsVisible: false as const,
  });
}

/**
 * Today Route reuses eligible AD_CLICK cards plus verified public opportunities.
 * Public opportunities are split by participation tier: IMMEDIATE (rolling
 * participation, no selection) and SCREENING_REQUIRED (application/qualification
 * needed, never shown as instant reward).
 */
// Backwards/alias exports for compatibility with alternate naming used by tests/CTO contracts.
export { buildAdClickFirstBrowse as buildAdClickFirstOpportunityBrowse };
export { buildAdClickFirstBrowse as buildOpportunityBrowse };
export { buildAdClickFirstOpportunityDetail as buildAdClickFirstOpportunityDetailViewModel };
export { buildAdClickFirstOpportunityDetail as buildOpportunityDetail };

export function buildAdClickFirstTodayRoute(
  candidates: readonly AdClickConsumerCandidate[],
  options: BuildAdClickFirstTodayRouteOptions = {},
): AdClickFirstTodayRouteViewModel {
  const cards = Object.freeze([...buildDefaultAdClickCards(candidates)].sort(byLowestActiveTime));
  const publicCards = displayablePublicOpportunityCards(options.publicOpportunities ?? []);
  const publicImmediateCards = Object.freeze(
    publicCards
      .filter((card) => card.todayTier === 'IMMEDIATE')
      .sort((a, b) => b.userValueScore - a.userValueScore),
  );
  const publicScreeningCards = Object.freeze(
    publicCards
      .filter((card) => card.todayTier === 'SCREENING_REQUIRED')
      .sort((a, b) => b.userValueScore - a.userValueScore),
  );
  const hasAnySupply = cards.length > 0 || publicImmediateCards.length > 0 || publicScreeningCards.length > 0;
  return Object.freeze({
    mode: 'TODAY_ROUTE_AD_CLICK_FIRST' as const,
    cards,
    emptyState: hasAnySupply ? null : ('NO_LIVE_REWARD_SUPPLY' as const),
    laterTierSuggestionsVisible: false as const,
    publicImmediateCards,
    publicScreeningCards,
  });
}

const BROWSE_CATEGORIES: ReadonlyArray<{ id: ConsumerBrowseCategory; label: string }> = Object.freeze([
  Object.freeze({ id: 'ALL' as const, label: '전체' }),
  Object.freeze({ id: 'AD_CLICK' as const, label: '광고·클릭·방문' }),
  Object.freeze({ id: 'SURVEY' as const, label: '설문·리서치' }),
  Object.freeze({ id: 'USABILITY' as const, label: '사용성 테스트' }),
  Object.freeze({ id: 'MICROTASK' as const, label: 'AI 데이터·마이크로태스크' }),
  Object.freeze({ id: 'SHORT_GIG' as const, label: '단기 온라인 작업' }),
]);

/** Public lane labels shown to consumers; the ad-click lane keeps its own activation policy. */
const PUBLIC_BROWSE_CATEGORY_IDS: ReadonlySet<string> = Object.freeze(
  new Set<string>(['SURVEY', 'USABILITY', 'MICROTASK', 'SHORT_GIG']),
);

export interface BuildAdClickFirstBrowseOptions {
  readonly category?: ConsumerBrowseCategory;
  readonly query?: string;
  readonly maxSeconds?: number | null;
  readonly publicOpportunities?: readonly PublicOpportunity[];
}

export interface BuildAdClickFirstTodayRouteOptions {
  readonly publicOpportunities?: readonly PublicOpportunity[];
}

export interface BuildAdClickFirstOpportunityDetailOptions {
  readonly publicOpportunities?: readonly PublicOpportunity[];
}

function publicCardMatchesQuery(card: PublicOpportunityCard, lowerQuery: string): boolean {
  return (
    card.titleKo.toLowerCase().includes(lowerQuery) ||
    card.vendor.toLowerCase().includes(lowerQuery)
  );
}

export function buildAdClickFirstBrowse(
  candidates: readonly AdClickConsumerCandidate[],
  options: BuildAdClickFirstBrowseOptions = {},
): AdClickFirstBrowseViewModel {
  const selectedCategory = options.category ?? 'ALL';
  const query = (options.query ?? '').trim();
  const maxSeconds = options.maxSeconds ?? null;

  const baseCards = [...buildDefaultAdClickCards(candidates)].sort(byLowestActiveTime);

  let filtered = baseCards;
  if (selectedCategory !== 'ALL' && selectedCategory !== 'AD_CLICK') {
    filtered = [];
  }
  if (maxSeconds !== null && Number.isFinite(maxSeconds) && maxSeconds > 0) {
    filtered = filtered.filter((card) => card.estimatedActiveSeconds <= maxSeconds);
  }
  if (query) {
    const lower = query.toLowerCase();
    filtered = filtered.filter((card) => card.title.toLowerCase().includes(lower));
  }
  const cards = Object.freeze(filtered);

  // Public lane: verified public opportunities only. The ad-click lane activation
  // policy is untouched; public categories become active with real verified supply.
  const allPublicCards = displayablePublicOpportunityCards(options.publicOpportunities ?? []);
  let publicCards: readonly PublicOpportunityCard[];
  if (selectedCategory === 'ALL') {
    publicCards = allPublicCards;
  } else if (selectedCategory === 'AD_CLICK') {
    publicCards = [];
  } else {
    publicCards = allPublicCards.filter((card) => card.category === selectedCategory);
  }
  if (query) {
    const lower = query.toLowerCase();
    publicCards = publicCards.filter((card) => publicCardMatchesQuery(card, lower));
  }
  publicCards = Object.freeze(
    [...publicCards].sort((a, b) => b.userValueScore - a.userValueScore),
  );

  const publicCountByCategory: Readonly<Record<string, number>> = Object.freeze(
    allPublicCards.reduce<Record<string, number>>(
      (acc, card) => {
        acc[card.category] = (acc[card.category] ?? 0) + 1;
        return acc;
      },
      {},
    ),
  );

  const hasPublicInput = (options.publicOpportunities ?? []).length > 0;
  const categories: readonly ConsumerBrowseCategoryItem[] = Object.freeze(
    BROWSE_CATEGORIES.map((cat) => {
      const count =
        cat.id === 'ALL'
          ? baseCards.length + allPublicCards.length
          : cat.id === 'AD_CLICK'
            ? baseCards.length
            : (publicCountByCategory[cat.id] ?? 0);
      const active = PUBLIC_BROWSE_CATEGORY_IDS.has(cat.id)
        ? count > 0
        : cat.id === 'AD_CLICK'
          ? baseCards.length > 0
          : true;
      return Object.freeze({
        id: cat.id,
        label: cat.label,
        active,
        count,
      });
    }),
  );

  return Object.freeze({
    mode: 'OPPORTUNITY_BROWSE_AD_CLICK_FIRST' as const,
    primaryNavigation: PRIMARY_NAVIGATION,
    selectedCategory,
    categories,
    cards,
    publicCards,
    filters: Object.freeze({ query, maxSeconds, category: selectedCategory }),
    emptyState: cards.length === 0 && publicCards.length === 0 ? 'NO_LIVE_REWARD_SUPPLY' as const : null,
    laterTierNotice: hasPublicInput
      ? '광고·클릭·방문 적립은 공급자 승인이 완료되면 표시됩니다.'
      : '광고·클릭·방문 적립만 현재 공개됩니다. 그 외 카테고리는 준비 중입니다.',
    publicSupplyNote:
      hasPublicInput && allPublicCards.length > 0
        ? '공개 기회는 업체에 직접 신청·참여하며 B64는 수익을 받지 않습니다.'
        : null,
    accountOnboardingVisibleToConsumer: false as const,
    laterTierNavigationVisible: false as const,
  });
}

export function buildAdClickFirstOpportunityDetail(
  candidates: readonly AdClickConsumerCandidate[],
  id: string,
  options: BuildAdClickFirstOpportunityDetailOptions = {},
): AdClickFirstOpportunityDetailViewModel {
  const cards = buildDefaultAdClickCards(candidates);
  const card = cards.find((c) => c.id === id) ?? null;
  const publicOpportunity =
    card === null
      ? ((options.publicOpportunities ?? []).find(
          (opportunity) => opportunity.id === id && isPublicOpportunityDisplayable(opportunity),
        ) ?? null)
      : null;
  const publicDetail = publicOpportunity ? toPublicOpportunityDetail(publicOpportunity) : null;
  const found = card !== null || publicDetail !== null;
  return Object.freeze({
    mode: 'OPPORTUNITY_DETAIL_AD_CLICK_FIRST' as const,
    primaryNavigation: PRIMARY_NAVIGATION,
    card,
    publicDetail,
    found,
    emptyState: found ? null : ('NO_LIVE_REWARD_SUPPLY' as const),
    accountOnboardingVisibleToConsumer: false as const,
    laterTierNavigationVisible: false as const,
  });
}
