/**
 * Local preview server for B64 consumer screens (screenshot capture only).
 * Wraps the compiled Worker fetch handler (npm run build first) in a node
 * http server so the checked-in docs/screenshots/theme-5822 captures stay
 * reproducible: node serve-local-preview.mjs, then open http://127.0.0.1:8791.
 * Local evidence tooling only — not part of the deployed Worker.
 */
import http from 'node:http';
import worker from './dist/src/worker.js';

const PORT = Number(process.env.PORT ?? 8791);

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
    const response = await worker.fetch(request);
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
  console.log(`B64 preview listening on http://127.0.0.1:${PORT}`);
});
