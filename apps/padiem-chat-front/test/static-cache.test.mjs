import test from 'node:test';
import assert from 'node:assert/strict';
import { createFront as realCreateFront } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  sign: async (request) => new Headers(request.headers),
  ...options,
});

const env = {
  FRONT_ORIGIN: "https://host.example",
  ASSETS: {
    async fetch(request) {
      const path = new URL(request.url).pathname;
      if (path === "/") {
        return new Response("<html>shell</html>", {
          headers: { "content-type": "text/html; charset=utf-8" },
        });
      }
      if (path === "/static/missing.js") {
        return new Response("not found", { status: 404 });
      }
      return new Response("export default 1;", {
        headers: { "content-type": "text/javascript" },
      });
    },
  },
  FALLBACK_MODE: "service",
};

test("a static script answer carries the session cache window", async () => {
  const handle = createFront({ fetchImpl: async () => { throw new Error("static must not reach COM2"); } });
  const response = await handle(new Request("https://chat.example.test/static/util-menu.js"), env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"),
    "private, max-age=300");
});

test("the html entry is never cached as static", async () => {
  const handle = createFront({ fetchImpl: async () => { throw new Error("no upstream in this test"); } });
  const home = await handle(new Request("https://chat.example.test/"), env);
  assert.notEqual(home.headers.get("cache-control"),
    "private, max-age=300");
});
