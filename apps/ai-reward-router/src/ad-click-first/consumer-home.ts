import {
  buildDefaultAdClickCards,
  type AdClickConsumerCandidate,
  type AdClickConsumerCard,
} from './consumer-card.js';

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
  readonly filters: AdClickFirstBrowseFilterState;
  readonly emptyState: AdClickFirstConsumerEmptyState | null;
  readonly laterTierNotice: string;
  readonly accountOnboardingVisibleToConsumer: false;
  readonly laterTierNavigationVisible: false;
}

export interface AdClickFirstOpportunityDetailViewModel {
  readonly mode: 'OPPORTUNITY_DETAIL_AD_CLICK_FIRST';
  readonly primaryNavigation: readonly ConsumerPrimaryNavItem[];
  readonly card: AdClickConsumerCard | null;
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
export function buildAdClickFirstConsumerHome(
  candidates: readonly AdClickConsumerCandidate[],
): AdClickFirstConsumerHomeViewModel {
  const cards = Object.freeze([...buildDefaultAdClickCards(candidates)].sort(byLowestActiveTime));
  return Object.freeze({
    mode: 'AD_CLICK_FIRST' as const,
    issueNumber: 1112 as const,
    primaryNavigation: PRIMARY_NAVIGATION,
    hero: Object.freeze({
      eyebrow: 'PADIEM AI Reward Router',
      title: '오늘의 추천 수익 기회',
      description: '검증된 조건과 보상만 보여드립니다.',
    }),
    sections: Object.freeze([
      Object.freeze({
        id: 'AVAILABLE_NOW' as const,
        title: '바로 가능한 적립',
        cards,
      }),
    ]),
    emptyState: cards.length === 0 ? 'NO_LIVE_REWARD_SUPPLY' as const : null,
    accountOnboardingVisibleToConsumer: false as const,
    laterTierNavigationVisible: false as const,
    laterTierSectionsVisible: false as const,
  });
}

/**
 * Today Route is intentionally narrow during P0: it only reuses already
 * eligible AD_CLICK cards and never falls back to survey/microtask/gig/job data.
 */
// Backwards/alias exports for compatibility with alternate naming used by tests/CTO contracts.
export { buildAdClickFirstBrowse as buildAdClickFirstOpportunityBrowse };
export { buildAdClickFirstBrowse as buildOpportunityBrowse };
export { buildAdClickFirstOpportunityDetail as buildAdClickFirstOpportunityDetailViewModel };
export { buildAdClickFirstOpportunityDetail as buildOpportunityDetail };

export function buildAdClickFirstTodayRoute(
  candidates: readonly AdClickConsumerCandidate[],
): AdClickFirstTodayRouteViewModel {
  const cards = Object.freeze([...buildDefaultAdClickCards(candidates)].sort(byLowestActiveTime));
  return Object.freeze({
    mode: 'TODAY_ROUTE_AD_CLICK_FIRST' as const,
    cards,
    emptyState: cards.length === 0 ? 'NO_LIVE_REWARD_SUPPLY' as const : null,
    laterTierSuggestionsVisible: false as const,
  });
}

const BROWSE_CATEGORIES: ReadonlyArray<{ id: ConsumerBrowseCategory; label: string; active: boolean }> = Object.freeze([
  Object.freeze({ id: 'ALL' as const, label: '전체', active: true }),
  Object.freeze({ id: 'AD_CLICK' as const, label: '광고·클릭·방문', active: true }),
  Object.freeze({ id: 'SURVEY' as const, label: '설문·리서치', active: false }),
  Object.freeze({ id: 'USABILITY' as const, label: '사용성 테스트', active: false }),
  Object.freeze({ id: 'MICROTASK' as const, label: 'AI 데이터·마이크로태스크', active: false }),
  Object.freeze({ id: 'SHORT_GIG' as const, label: '단기 온라인 작업', active: false }),
]);

export interface BuildAdClickFirstBrowseOptions {
  readonly category?: ConsumerBrowseCategory;
  readonly query?: string;
  readonly maxSeconds?: number | null;
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

  const categories: readonly ConsumerBrowseCategoryItem[] = Object.freeze(
    BROWSE_CATEGORIES.map((cat) =>
      Object.freeze({
        id: cat.id,
        label: cat.label,
        active: cat.active,
        count: cat.id === 'AD_CLICK' || cat.id === 'ALL' ? baseCards.length : 0,
      }),
    ),
  );

  return Object.freeze({
    mode: 'OPPORTUNITY_BROWSE_AD_CLICK_FIRST' as const,
    primaryNavigation: PRIMARY_NAVIGATION,
    selectedCategory,
    categories,
    cards,
    filters: Object.freeze({ query, maxSeconds, category: selectedCategory }),
    emptyState: cards.length === 0 ? 'NO_LIVE_REWARD_SUPPLY' as const : null,
    laterTierNotice: '광고·클릭·방문 적립만 현재 공개됩니다. 그 외 카테고리는 준비 중입니다.',
    accountOnboardingVisibleToConsumer: false as const,
    laterTierNavigationVisible: false as const,
  });
}

export function buildAdClickFirstOpportunityDetail(
  candidates: readonly AdClickConsumerCandidate[],
  id: string,
): AdClickFirstOpportunityDetailViewModel {
  const cards = buildDefaultAdClickCards(candidates);
  const card = cards.find((c) => c.id === id) ?? null;
  return Object.freeze({
    mode: 'OPPORTUNITY_DETAIL_AD_CLICK_FIRST' as const,
    primaryNavigation: PRIMARY_NAVIGATION,
    card,
    found: card !== null,
    emptyState: card === null ? 'NO_LIVE_REWARD_SUPPLY' as const : null,
    accountOnboardingVisibleToConsumer: false as const,
    laterTierNavigationVisible: false as const,
  });
}
