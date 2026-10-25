/**
 * Local preview server for B64 consumer screens (screenshot capture only).
 * Wraps the compiled Worker fetch handler (npm run build first) in a node
 * http server so the checked-in docs/screenshots captures stay reproducible:
 * node serve-local-preview.mjs, then open http://127.0.0.1:8791.
 *
 * B64_TEST_AUTH=1 runs an authenticated journey harness: a FIXED test user
 * (usr_e2e_preview_user) is injected through the same trusted server-side
 * resolveAuth seam the production worker uses, backed by the in-memory
 * repository. This is local evidence tooling for UI-journey screenshots only —
 * it is not a second login scheme, never reads client-controlled identity
 * headers beyond the injected resolver, and is not part of the deployed
 * Worker (which keeps failing closed without the real bindings).
 */
import http from 'node:http';
import worker from './dist/src/worker.js';
import { createConsumerHttpHandler } from './dist/src/http/consumer-http.js';
import { loadVerifiedPublicOpportunities } from './dist/src/public-supply/verified-public-opportunities.js';
import { createTestAuthResolver } from './dist/src/income-pipeline/auth.js';
import { InMemoryUserIncomeRepository } from './dist/src/income-pipeline/store.js';

const PORT = Number(process.env.PORT ?? 8791);
const TEST_AUTH = process.env.B64_TEST_AUTH === '1';

let handleRequest;
if (TEST_AUTH) {
  handleRequest = createConsumerHttpHandler({
    loadCandidates: () => [],
    loadPublicOpportunities: loadVerifiedPublicOpportunities,
    resolveAuth: createTestAuthResolver('usr_e2e_preview_user'),
    incomeRepository: new InMemoryUserIncomeRepository(),
  });
} else {
  handleRequest = worker.fetch;
}

const server = http.createServer(async (req, res) => {
  try {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = chunks.length > 0 ? Buffer.concat(chunks) : undefined;
    const request = new Request(`http://127.0.0.1:${PORT}${req.url}`, {
      method: req.method,
      headers: req.headers,
      body: req.method === 'GET' || req.method === 'HEAD' ? undefined : body,
    });
    const response = await handleRequest(request);
    res.statusCode = response.status;
    for (const [name, value] of response.headers) {
      if (name === 'set-cookie') {
        for (const cookie of response.headers.getSetCookie()) res.appendHeader('set-cookie', cookie);
      } else {
        res.setHeader(name, value);
      }
    }
    const out = response.body ? Buffer.from(await response.arrayBuffer()) : null;
    res.end(out);
  } catch (error) {
    res.statusCode = 500;
    res.end(String(error));
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`B64 preview listening on http://127.0.0.1:${PORT}${TEST_AUTH ? ' (authenticated journey harness)' : ''}`);
});
