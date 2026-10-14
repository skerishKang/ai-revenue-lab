/* B66 #3396: authenticated guided-draft transport. No browser owner authority. */
(() => {
  "use strict";
  const URL = "/api/padiem/b66/guided-draft";
  async function request(method, state) {
    try {
      const init = { method, credentials: "same-origin", cache: "no-store" };
      if (method === "PUT") {
        init.headers = { "Content-Type": "application/json" };
        init.body = JSON.stringify(state);
      }
      const response = await fetch(URL, init);
      const payload = await response.json().catch(() => null);
      if (!response.ok || payload?.ok !== true) {
        return { ok: false, status: response.status, error: payload?.error?.code || "guided_state_unavailable" };
      }
      return { ok: true, state: payload.state || null };
    } catch (_) {
      return { ok: false, error: "guided_state_network_unavailable" };
    }
  }
  const HISTORY = "/api/padiem/b66/guided-conversations";
  const GUIDED_ID = /^gdt_[a-f0-9]{32}$/;
  async function historyRequest(method, id) {
    if (id != null && !GUIDED_ID.test(String(id))) return { ok: false, error: "invalid_guided_conversation_id" };
    try {
      const response = await fetch(HISTORY + (id ? "/" + encodeURIComponent(id) : ""), {
        method, credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json" }
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || data?.ok !== true) {
        return { ok: false, error: data?.error?.code || "guided_history_unavailable" };
      }
      return { ok: true, conversations: data.conversations, conversation: data.conversation };
    } catch (_) {
      return { ok: false, error: "guided_history_network_unavailable" };
    }
  }
  window.B66GuidedDraftServer = Object.freeze({
    load: () => request("GET"),
    save: (state) => request("PUT", state),
    clear: () => request("DELETE"),
    listConversations: () => historyRequest("GET"),
    loadConversation: (id) => historyRequest("GET", id),
    deleteConversation: (id) => historyRequest("DELETE", id)
  });
})();
