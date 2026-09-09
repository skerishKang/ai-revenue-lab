import { Container, getContainer } from "@cloudflare/containers";
import { env as workerEnv } from "cloudflare:workers";

/**
 * Cloudflare container wrapper for the existing Living Fiction FastAPI app.
 *
 * The container receives only server-owned Worker bindings. No browser payload
 * can provide database credentials, session secrets, or AI-provider authority.
 */
export class LivingFictionContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "5m";

  envVars = {
    LF_ENV: "production",
    LF_DATABASE_BACKEND: "postgres",
    LF_DATABASE_URL: workerEnv.LF_DATABASE_URL,
    LF_ADMIN_SECRET: workerEnv.LF_ADMIN_SECRET,
    LF_CREDENTIAL_HMAC_KEY: workerEnv.LF_CREDENTIAL_HMAC_KEY,
    LF_SESSION_HMAC_KEY: workerEnv.LF_SESSION_HMAC_KEY,
    LF_ALLOWED_ORIGINS: workerEnv.LF_ALLOWED_ORIGINS,
    LF_AI_PROVIDER: "mock",
    LF_AI_MODEL: "mock-living-fiction-v1",
  };
}

export default {
  async fetch(request, env) {
    // One stable service instance is sufficient for the migration parity gate;
    // application state remains in Neon, not in the container filesystem.
    const instance = getContainer(env.LIVING_FICTION_CONTAINER, "primary");
    return instance.fetch(request);
  },
};
