import { createPublicSupplyConsumerHttpHandler } from './http/consumer-http.js';

const handleRequest = createPublicSupplyConsumerHttpHandler();

/**
 * Deployment-safe default Worker entrypoint.
 *
 * The ad-click provider lane stays intentionally zero-supply: no provider is
 * LIVE_AUTHORIZED yet, so `/` renders the honest P0 state with zero real ad
 * reward cards until OWNER activation and production configuration complete.
 *
 * The public-supply lane serves manually curated, publicly verified
 * opportunities on /browse, /today and /detail. These link users to official
 * provider pages, pay PADIEM nothing, and never grant provider authority.
 */
export default {
  fetch(request: Request): Promise<Response> {
    return handleRequest(request);
  },
};
