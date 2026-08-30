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
      eyebrow: '가장 쉬운 적립부터',
      title: '지금 바로 할 수 있는 적립',
      description: '광고보기·클릭·방문처럼 짧게 끝나는 적립만 먼저 보여드려요.',
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
