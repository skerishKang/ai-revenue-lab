import { createEmptySupplyConsumerHttpHandler } from './http/consumer-http.js';

const handleRequest = createEmptySupplyConsumerHttpHandler();

/**
 * Deployment-safe default Worker entrypoint.
 *
 * Real provider supply is intentionally not wired here. Until OWNER activation and
 * production configuration are complete, `/` and `/earn` render the honest P0
 * zero-supply state rather than fabricated earning inventory.
 */
export default {
  fetch(request: Request): Promise<Response> {
    return handleRequest(request);
  },
};
