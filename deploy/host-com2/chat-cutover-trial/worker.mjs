// Harmless fixture only. No storage, bindings, upstream fetch or mutation.
export default {
  fetch(request, env) {
    const allowed = request.method === "GET" && new URL(request.url).pathname === "/__cutover_trial";
    if (!allowed) return new Response("Not found", { status: 404 });
    if (env.TRIAL_WORKER !== "A" && env.TRIAL_WORKER !== "B") {
      return new Response("Fixture misconfigured", { status: 503 });
    }
    return Response.json({ trial: "chat-domain-move", worker: env.TRIAL_WORKER }, {
      headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" },
    });
  },
};
