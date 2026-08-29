export const PRODUCT_ID = 'B64' as const;
export const PRODUCT_SLUG = 'ai-reward-router' as const;

export const ROUTING_MODES = {
  TODAY_ROUTE: 'TODAY_ROUTE',
  INCOME_PIPELINE: 'INCOME_PIPELINE',
} as const;

export type RoutingMode = (typeof ROUTING_MODES)[keyof typeof ROUTING_MODES];

export const PRODUCT_IDENTITY = Object.freeze({
  businessId: PRODUCT_ID,
  slug: PRODUCT_SLUG,
  lifecycle: 'incubation',
  initialMarketPriority: 'KOREA_PRIORITY',
  supplyScope: 'GLOBAL_BY_DESIGN',
  routingModes: Object.freeze(Object.values(ROUTING_MODES)),
  userValueScoreSeparateFromMonetizationScore: true,
  walletRequiredForW0: false,
});
