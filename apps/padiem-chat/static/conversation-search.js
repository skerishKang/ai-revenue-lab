(() => {
  "use strict";

  // #4471: owner-scoped conversation search behind the sidebar Search entry.
  //
  // Scope contract (do not widen):
  //   - Owns #sidebarSearchButton behavior only.
  //   - Never reads or toggles #webSearchButton / #webSearchStarterButton /
  //     #deepResearchButton, and never changes the center "웹에서 찾아줘" card.
  //   - Fail-closed: the entry stays disabled until the canonical capability
  //     projection reports a signed-in owner with a ready history store. No
  //     browser storage API, cookie, or credential token is read here.
  //   - Opening a hit calls the canonical saved-conversation loader published by
  //     app.js, so a hit outside the recent-list page still opens. This module
  //     never fetches a conversation itself and never infers Claw authority.

  const SEARCH_ENDPOINT = "/api/conversations/search";
  const MAX_QUERY_CHARS = 80;
  const DEBOUNCE_MS = 250;

  const sidebarSearchButton = document.getElementById("sidebarSearchButton");
  const historySection = document.getElementById("historySection");
  const historyList = document.getElementById("historyList");
  if (!sidebarSearchButton || !historySection || !historyList) return;

  let available = false;
  let searchOpen = false;
  let generation = 0;
  let authSignature = "";
  let debounceTimer = null;

  // This module owns the entry's title/aria-label in both states (hold and
  // enabled), so the static locale bindings must not fight it.
  sidebarSearchButton.removeAttribute("data-locale-title");
  sidebarSearchButton.removeAttribute("data-locale-aria-label");

  function copy(ko, en) {
    return document.documentElement.lang.toLowerCase().startsWith("en") ? en : ko;
  }

  // The panel lives inside the existing recent-history section, so a hit lands
  // in the same visual column the owner already reads history from.
  const panel = document.createElement("div");
  panel.id = "conversationSearchPanel";
  panel.className = "conversation-search-panel";
  panel.hidden = true;

  const input = document.createElement("input");
  input.type = "search";
  input.id = "conversationSearchInput";
  input.className = "conversation-search-input";
  input.maxLength = MAX_QUERY_CHARS;
  input.setAttribute("autocomplete", "off");

  const status = document.createElement("p");
  status.id = "conversationSearchStatus";
  status.className = "history-empty";
  status.setAttribute("aria-live", "polite");
  status.hidden = true;

  const results = document.createElement("div");
  results.id = "conversationSearchResults";
  results.className = "conversation-search-results";

  panel.append(input, status, results);
  historySection.insertBefore(panel, historyList);

  function setStatus(text) {
    status.textContent = text;
    status.hidden = !text;
  }

  let renderStatus = () => setStatus("");

  function showStatus(ko, en) {
    renderStatus = () => setStatus(copy(ko, en));
    renderStatus();
  }

  function clearStatus() {
    renderStatus = () => setStatus("");
    setStatus("");
  }

  // One monotonic generation per user-visible intent. Any in-flight response
  // carrying an older generation is dropped before it can touch the DOM, so a
  // superseded query can never paint over a newer one or survive a session flip.
  function invalidate() {
    generation += 1;
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    results.replaceChildren();
    clearStatus();
  }

  function renderStaticCopy() {
    const label = copy("대화 검색", "Search conversations");
    input.placeholder = label;
    input.setAttribute("aria-label", label);
  }

  function renderButtonChrome() {
    const label = available
      ? copy("대화 검색", "Search conversations")
      : copy("대화 검색 준비 중", "Conversation search coming soon");
    sidebarSearchButton.setAttribute("title", label);
    sidebarSearchButton.setAttribute("aria-label", label);
  }

  function setPressed(pressed) {
    sidebarSearchButton.setAttribute("aria-pressed", pressed ? "true" : "false");
    sidebarSearchButton.classList.toggle("is-active", pressed);
  }

  function applyAvailability() {
    sidebarSearchButton.disabled = !available;
    sidebarSearchButton.setAttribute("aria-disabled", available ? "false" : "true");
    renderButtonChrome();
    if (!available) closeSearch();
  }

  // Availability: signed in AND server history ready — read from the canonical
  // capability projection (the same source the account nav uses), never from
  // client storage. Fail-closed until it reports ready.
  function applyAuthState(auth) {
    available = Boolean(
      auth && auth.loaded === true && auth.authenticated === true && auth.historyReady === true,
    );
    // The projection re-dispatches on every window focus with the same values,
    // so only a real transition may wipe the panel; otherwise live results would
    // vanish while the owner is still reading them.
    const signature = auth
      ? `${auth.loaded === true}/${auth.authenticated === true}/${auth.historyReady === true}`
      : "";
    const changed = signature !== authSignature;
    authSignature = signature;
    // Login as well as logout crosses here, so a new session can never inherit
    // the previous owner's rendered hits.
    if (changed) invalidate();
    applyAvailability();
  }

  function readCapabilityAuth() {
    const api = window.PadiemProductCapabilities;
    if (!api || typeof api.get !== "function") return null;
    try {
      const state = api.get();
      return state && state.auth ? state.auth : null;
    } catch (_) {
      return null;
    }
  }

  function renderResults(conversations, query) {
    results.replaceChildren();
    if (!conversations.length) {
      showStatus(`“${query}” 검색 결과가 없습니다.`, `No results for “${query}”.`);
      return;
    }
    clearStatus();
    conversations.forEach((conversation) => {
      if (!conversation || typeof conversation.id !== "string" || typeof conversation.title !== "string") return;
      const row = document.createElement("button");
      row.type = "button";
      row.className = "recent-item history-item conversation-search-hit";
      row.dataset.conversationId = conversation.id;
      const title = document.createElement("span");
      title.className = "conversation-search-title";
      title.textContent = conversation.title;
      row.appendChild(title);
      if (typeof conversation.snippet === "string" && conversation.snippet) {
        const snippet = document.createElement("span");
        snippet.className = "conversation-search-snippet";
        snippet.textContent = conversation.snippet;
        row.appendChild(snippet);
      }
      row.addEventListener("click", () => openHit(conversation.id));
      results.appendChild(row);
    });
  }

  // The canonical loader already owns the auth guard, the inFlight lock, project
  // restore and the server-verified Claw set, so an older hit outside the recent
  // page opens exactly like a listed one. No conversation fetch happens here.
  function openHit(conversationId) {
    if (!/^chat_[a-f0-9]{32}$/.test(conversationId)) return;
    const opener = window.PadiemChatConversationOpener;
    if (!opener || typeof opener.open !== "function") return;
    opener.open(conversationId);
  }

  async function runSearch(rawQuery, seq) {
    const query = rawQuery.replace(/\s+/g, " ").trim().slice(0, MAX_QUERY_CHARS);
    if (!query || seq !== generation) return;
    try {
      const response = await fetch(`${SEARCH_ENDPOINT}?q=${encodeURIComponent(query)}`, {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (seq !== generation) return; // superseded by a newer query, a close or a session flip
      if (!response.ok || !data || !Array.isArray(data.conversations)) {
        results.replaceChildren();
        showStatus("검색을 사용할 수 없습니다.", "Search is unavailable.");
        return;
      }
      renderResults(data.conversations, query);
    } catch (_) {
      if (seq !== generation) return;
      results.replaceChildren();
      showStatus("검색을 사용할 수 없습니다.", "Search is unavailable.");
    }
  }

  input.addEventListener("input", () => {
    // Supersede at the keystroke, not when the debounced call finally starts,
    // so a response to the previous query cannot land over the new intent.
    const seq = ++generation;
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    const rawQuery = input.value;
    results.replaceChildren();
    if (!rawQuery.trim()) {
      clearStatus();
      return;
    }
    showStatus("검색 중…", "Searching…");
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      runSearch(rawQuery, seq);
    }, DEBOUNCE_MS);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSearch();
  });

  function openSearch() {
    if (!available) return;
    searchOpen = true;
    panel.hidden = false;
    setPressed(true);
    input.focus();
  }

  function closeSearch() {
    invalidate();
    input.value = "";
    searchOpen = false;
    panel.hidden = true;
    setPressed(false);
  }

  sidebarSearchButton.addEventListener("click", () => {
    if (!available) return;
    if (searchOpen) {
      closeSearch();
    } else {
      openSearch();
    }
  });

  // Availability follows the canonical capability projection, so it re-checks
  // when that projection changes — never on a timer.
  window.addEventListener("padiem:capabilitychange", (event) => {
    const auth = event && event.detail ? event.detail.auth : null;
    applyAuthState(auth || readCapabilityAuth());
  });

  // Language switches re-render the copy this module owns.
  window.addEventListener("padiem:localechange", () => {
    renderStaticCopy();
    renderButtonChrome();
    renderStatus();
  });

  renderStaticCopy();
  applyAuthState(readCapabilityAuth());

  window.PadiemConversationSearch = Object.freeze({
    isAvailable: () => available,
    isOpen: () => searchOpen,
  });
})();
