import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/**
 * #5298 — React independent clone of the Padiem Chat / Claw first screen.
 *
 * The clone never writes into `apps/padiem-chat/`. It only *reads* the
 * operational design tokens and shared assets from there so the first screen
 * is comparable with the running product instead of being a re-interpretation.
 */

/** The nearest ancestor that is a git working tree. */
function findRepoRoot(start: string): string | null {
  let current = start;
  for (let depth = 0; depth < 8; depth += 1) {
    if (existsSync(join(current, ".git"))) return current;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return null;
}

/**
 * The revision the served bundle was built from.
 *
 * A dev server that still runs from an older working tree looks exactly like a
 * fresh one, so the served revision is published and can be compared with
 * `git rev-parse HEAD` before a verification run is trusted. A dirty working
 * tree is marked, so a stale server is detectable instead of silently reused.
 */
function resolveRevision(): string {
  // The config file is bundled before it runs, so `import.meta.url` no longer
  // points at this file. The working directory is the project root instead.
  const root = findRepoRoot(process.cwd());
  if (!root) return "unknown";
  try {
    const head = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    let dirty = true;
    try {
      dirty =
        execFileSync("git", ["status", "--porcelain"], {
          cwd: root,
          encoding: "utf8",
          stdio: ["ignore", "pipe", "ignore"],
        }).trim().length > 0;
    } catch {
      dirty = true;
    }
    return dirty ? `${head}-dirty` : head;
  } catch {
    return "unknown";
  }
}

const revision = resolveRevision();

/**
 * The Chat API the clone talks to.
 *
 * There is no default on purpose. Without an explicit base URL the clone
 * stays in its offline fixture mode and never reaches a live API from a
 * developer machine by accident. The base URL is also the origin the
 * operational same-origin guard expects, so the proxy sends it as `Origin`.
 */
const apiBaseUrl = (process.env.PADIEM_CHAT_API_BASE_URL ?? "").trim().replace(/\/+$/, "");

const apiProxy = apiBaseUrl
  ? {
      "/api": {
        target: apiBaseUrl,
        // The upstream request must carry the API host. The dev server's own
        // host check runs on the incoming request, so the incoming Host stays
        // the dev origin and only the forwarded request is rewritten.
        changeOrigin: true,
        // The session cookie is issued for the API host. The clone is served
        // from the dev origin, so the domain attribute is dropped and the
        // cookie becomes host-only for the dev origin.
        cookieDomainRewrite: "",
        headers: {
          // The reviewed same-origin guard compares the request Origin with
          // the server's own public base URL, never with the request host.
          Origin: apiBaseUrl,
        },
      },
      "/health": {
        target: apiBaseUrl,
        changeOrigin: true,
        headers: { Origin: apiBaseUrl },
      },
    }
  : undefined;

/**
 * Answers the auth status probe when no API is configured.
 *
 * The clone asks `/api/auth/status` to learn whether a real API is reachable.
 * Without this the dev server would answer 404, which the browser logs as a
 * console error, and the clone would learn the same thing from a failing
 * request instead of from a well-formed answer. The projection says the API is
 * not ready, so the clone stays in its offline mode and says so.
 */
function offlineAuthStatusPlugin() {
  return {
    name: "padiem-chat-react-offline-auth-status",
    configureServer(server: { middlewares: { use: (fn: unknown) => void } }) {
      server.middlewares.use((req: { url?: string }, res: {
        setHeader: (name: string, value: string) => void;
        end: (body: string) => void;
      }, next: () => void) => {
        const path = req.url?.split("?")[0];
        if (path !== "/api/auth/status" && path !== "/health") {
          next();
          return;
        }
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.setHeader("Cache-Control", "no-store");
        if (path === "/health") {
          res.end(JSON.stringify({ status: "offline", app: "padiem-chat-react" }));
          return;
        }
        res.end(
          JSON.stringify({
            ready: false,
            authenticated: false,
            history_ready: false,
            user: null,
            model_requires_session: true,
            session_state: "unavailable",
            methods: {},
          }),
        );
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), ...(apiBaseUrl ? [] : [offlineAuthStatusPlugin()])],
  define: {
    __APP_REVISION__: JSON.stringify(revision),
  },
  server: {
    port: 5174,
    // A busy port must fail the start instead of silently moving to another
    // port: a server on 5176 is invisible to a check that probes 5174, and the
    // verification would run against a stale server.
    strictPort: true,
    proxy: apiProxy,
    fs: {
      // The operational stylesheets and the canonical shared composer core live
      // in sibling directories of this repository.
      allow: ["..", "../.."],
    },
  },
  preview: {
    port: 4174,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // The operational stylesheets contain a trailing comma inside one
    // `box-shadow` declaration. Browsers accept it; lightningcss rejects it.
    // The operational app is never edited, so the clone minifies with esbuild
    // instead of failing the production build.
    cssMinify: "esbuild",
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
