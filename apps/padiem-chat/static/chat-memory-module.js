// R5 A2 - approved-memory review & list/detail section moved out of the app.js
// closure under B1's four rules: (a) own DOM/state declarations live inside
// create() without touching deps, (b) top-level listener and window-contract
// wiring run from app.js at their original positions, (c) shared state/DOM is
// read through the shared app context, (d) module API registers on app.provide.
(() => {
  "use strict";
  window.PadiemChatMemoryModule = {
    create(deps) {
      // Approved-memory review UI (#2340)
      const clawApprovedMemory = document.getElementById("clawApprovedMemory");
      // #4488 Phase A: the approved-memory panel is progressive disclosure on the
      // Claw entry; its <details> wrapper is hidden whenever the panel is.
      const clawApprovedDisclosure = document.getElementById("clawApprovedDisclosure");
      const clawApprovedRefresh = document.getElementById("clawApprovedRefresh");
      const clawApprovedLoading = document.getElementById("clawApprovedLoading");
      const clawApprovedError = document.getElementById("clawApprovedError");
      const clawApprovedList = document.getElementById("clawApprovedList");
      const clawApprovedEmpty = document.getElementById("clawApprovedEmpty");

      let approvedMemoryInFlight = false;

      function setApprovedMemoryStatus(message, state, code = "") {
        if (!clawApprovedError) return;
        if (!message) {
          clawApprovedError.hidden = true;
          clawApprovedError.textContent = "";
          clawApprovedError.removeAttribute("data-state");
          return;
        }
        clawApprovedError.hidden = false;
        clawApprovedError.textContent = message;
        const reference = deps.failureCodeNote(code, "");
        if (reference) clawApprovedError.appendChild(reference);
        if (state) clawApprovedError.dataset.state = state;
        else clawApprovedError.removeAttribute("data-state");
      }

      // Proposal review surface: rendered from preview memory_proposals. Approve is
      // impossible until the user explicitly approves; reject never persists.
      function renderMemoryProposalReview(proposals) {
        if (!deps.clawMemoryReview) return;
        deps.clawMemoryReview.replaceChildren();
        if (!Array.isArray(proposals) || proposals.length === 0) {
          deps.clawMemoryReview.hidden = true;
          return;
        }
        const heading = document.createElement("h3");
        heading.className = "claw-memory-review-title";
        heading.textContent = deps.clawT("claw-memory-review-title");
        deps.clawMemoryReview.appendChild(heading);
        proposals.forEach((proposal) => {
          if (!proposal || typeof proposal !== "object") return;
          const safe = {
            type: typeof proposal.type === "string" ? proposal.type : "",
            name: typeof proposal.name === "string" ? proposal.name : "",
            note: typeof proposal.note === "string" ? proposal.note : "",
            source_channel: typeof proposal.source_channel === "string" ? proposal.source_channel : "",
          };
          const card = document.createElement("div");
          card.className = "claw-memory-proposal";
          const title = document.createElement("strong");
          title.className = "claw-memory-proposal-name";
          title.textContent = safe.name;
          const meta = document.createElement("span");
          meta.className = "claw-memory-proposal-type";
          meta.textContent = safe.type;
          const note = document.createElement("p");
          note.className = "claw-memory-proposal-note";
          note.textContent = safe.note;
          const actions = document.createElement("div");
          actions.className = "claw-memory-proposal-actions";
          const approveBtn = document.createElement("button");
          approveBtn.type = "button";
          approveBtn.className = "claw-memory-approve";
          approveBtn.textContent = deps.clawT("claw-memory-approve");
          approveBtn.addEventListener("click", () => approveProposal(safe));
          const rejectBtn = document.createElement("button");
          rejectBtn.type = "button";
          rejectBtn.className = "claw-memory-reject";
          rejectBtn.textContent = deps.clawT("claw-memory-reject");
          rejectBtn.addEventListener("click", () => rejectProposal(safe));
          actions.append(approveBtn, rejectBtn);
          card.append(title, meta, note, actions);
          deps.clawMemoryReview.appendChild(card);
        });
        deps.clawMemoryReview.hidden = false;
      }

      function proposalBody(proposal) {
        return { type: proposal.type, name: proposal.name, note: proposal.note || null, source_channel: proposal.source_channel || null };
      }

      async function approveProposal(proposal) {
        if (approvedMemoryInFlight) return;
        approvedMemoryInFlight = true;
        setApprovedMemoryStatus("", "");
        try {
          const response = await fetch("/api/claw/memory/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            cache: "no-store",
            body: JSON.stringify({ approved: true, proposal: proposalBody(proposal) }),
          });
          const data = await response.json().catch(() => null);
          if (!response.ok || !data || data.ok !== true || !data.memory) {
            throw deps.mappedUiError(deps.approvedMemoryErrorMessage(data, response), data);
          }
          await fetchApprovedMemoryList();
        } catch (error) {
          setApprovedMemoryStatus(deps.safeLocalUiMessage(error, deps.clawT("claw-memory-error-generic")), "error", error?.code);
        } finally {
          approvedMemoryInFlight = false;
        }
      }

      async function rejectProposal(proposal) {
        if (approvedMemoryInFlight) return;
        approvedMemoryInFlight = true;
        setApprovedMemoryStatus("", "");
        try {
          const response = await fetch("/api/claw/memory/reject", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            cache: "no-store",
            body: JSON.stringify({ proposal: proposalBody(proposal) }),
          });
          const data = await response.json().catch(() => null);
          if (!response.ok || !data || data.ok !== true || data.persisted !== false) {
            throw deps.mappedUiError(deps.approvedMemoryErrorMessage(data, response), data);
          }
          await fetchApprovedMemoryList();
        } catch (error) {
          setApprovedMemoryStatus(deps.safeLocalUiMessage(error, deps.clawT("claw-memory-error-generic")), "error", error?.code);
        } finally {
          approvedMemoryInFlight = false;
        }
      }

      function renderApprovedMemoryCard(memory) {
        const card = document.createElement("div");
        card.className = "claw-approved-card";
        card.dataset.memoryId = memory.memory_id || "";

        const head = document.createElement("div");
        head.className = "claw-approved-card-head";
        const title = document.createElement("strong");
        title.className = "claw-approved-card-title";
        title.textContent = memory.name || "";
        const badge = document.createElement("span");
        badge.className = "claw-approved-card-badge";
        badge.textContent = memory.status === "approved" ? deps.clawT("claw-memory-status-approved") : deps.uiT("status-unknown");
        head.append(title, badge);

        const meta = document.createElement("div");
        meta.className = "claw-approved-card-meta";
        const memoryTypeKey = `claw-memory-type-${memory.memory_type || ""}`;
        const memoryType = memory.memory_type ? deps.clawT(memoryTypeKey) : "";
        meta.textContent = `${memoryType === memoryTypeKey ? memory.memory_type : memoryType} · ${memory.created_at || ""}`;

        const note = document.createElement("p");
        note.className = "claw-approved-card-note";
        note.textContent = memory.note || "";

        const actions = document.createElement("div");
        actions.className = "claw-approved-card-actions";
        const detailBtn = document.createElement("button");
        detailBtn.type = "button";
        detailBtn.className = "claw-approved-action";
        detailBtn.textContent = deps.clawT("claw-memory-detail");
        detailBtn.addEventListener("click", () => {
          const id = card.dataset.memoryId;
          if (id) loadApprovedMemoryDetail(id);
        });
        actions.appendChild(detailBtn);
        card.append(head, meta, note, actions);
        return card;
      }

      function renderApprovedMemoryDetail(memory) {
        const existing = clawApprovedList?.querySelector(".claw-approved-detail");
        if (existing) existing.remove();
        const detail = document.createElement("div");
        detail.className = "claw-approved-detail";
        const rows = [
          { label: deps.clawT("claw-memory-type"), value: memory.memory_type || "" },
          { label: deps.clawT("claw-memory-name"), value: memory.name || "" },
          { label: deps.clawT("claw-memory-note"), value: memory.note || "" },
          { label: deps.clawT("claw-memory-channel"), value: memory.source_channel || "" },
          { label: deps.clawT("claw-memory-status"), value: memory.status === "approved" ? deps.clawT("claw-memory-status-approved") : deps.uiT("status-unknown") },
          { label: deps.clawT("claw-memory-created"), value: memory.created_at || "" },
          { label: deps.clawT("claw-memory-updated"), value: memory.updated_at || "" },
        ];
        rows.forEach((row) => {
          const rowEl = document.createElement("div");
          rowEl.className = "claw-approved-detail-row";
          const label = document.createElement("span");
          label.className = "claw-approved-detail-label";
          label.textContent = row.label;
          const value = document.createElement("span");
          value.className = "claw-approved-detail-value";
          value.textContent = row.value;
          rowEl.append(label, value);
          detail.appendChild(rowEl);
        });
        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.className = "claw-approved-action";
        closeBtn.textContent = deps.clawT("claw-memory-close");
        closeBtn.addEventListener("click", () => {
          detail.remove();
          loadApprovedMemoryList();
        });
        detail.appendChild(closeBtn);
        clawApprovedList?.appendChild(detail);
      }

      // Unguarded fetch: callers hold the single-flight flag while awaiting this.
      async function fetchApprovedMemoryList() {
        if (!clawApprovedMemory) return;
        setApprovedMemoryStatus("", "");
        if (clawApprovedLoading) clawApprovedLoading.hidden = false;
        if (clawApprovedList) clawApprovedList.hidden = true;
        if (clawApprovedEmpty) clawApprovedEmpty.hidden = true;
        if (clawApprovedList) clawApprovedList.replaceChildren();
        try {
          const response = await fetch("/api/claw/memory", { headers: { "Accept": "application/json" }, cache: "no-store" });
          const data = await response.json().catch(() => null);
          if (!response.ok || !data || !Array.isArray(data.memories)) {
            throw deps.mappedUiError(deps.approvedMemoryErrorMessage(data, response), data);
          }
          if (clawApprovedLoading) clawApprovedLoading.hidden = true;
          if (clawApprovedList) clawApprovedList.hidden = false;
          if (data.memories.length === 0) {
            if (clawApprovedEmpty) clawApprovedEmpty.hidden = false;
            return;
          }
          data.memories.forEach((memory) => {
            if (!memory || typeof memory.memory_id !== "string") return;
            clawApprovedList?.appendChild(renderApprovedMemoryCard(memory));
          });
          // #5882: when the server returns a next cursor, append "load more" and keep the cursor on the button.
          if (clawApprovedList && typeof data.next_cursor === "string" && data.next_cursor) {
            const more = document.createElement("button");
            more.type = "button";
            more.className = "recent-item memory-more";
            more.id = "clawApprovedMore";
            more.dataset.cursor = data.next_cursor;
            more.textContent = deps.uiT("projects-more");
            more.addEventListener("click", () => { void loadMoreApprovedMemories(more.dataset.cursor); });
            clawApprovedList.appendChild(more);
          }
        } catch (error) {
          if (clawApprovedLoading) clawApprovedLoading.hidden = true;
          setApprovedMemoryStatus(deps.safeLocalUiMessage(error, deps.clawT("claw-memory-error-generic")), "error", error?.code);
        }
      }

      async function loadApprovedMemoryList() {
        if (approvedMemoryInFlight) return;
        approvedMemoryInFlight = true;
        try {
          await fetchApprovedMemoryList();
        } finally {
          approvedMemoryInFlight = false;
        }
      }

      async function loadMoreApprovedMemories(cursor) {
        if (!cursor || approvedMemoryInFlight || !clawApprovedList) return;
        approvedMemoryInFlight = true;
        const more = document.getElementById("clawApprovedMore");
        if (more) more.disabled = true;
        try {
          const response = await fetch(
            `/api/claw/memory?cursor=${encodeURIComponent(cursor)}`,
            { headers: { "Accept": "application/json" }, cache: "no-store" },
          );
          const data = await response.json().catch(() => null);
          if (response.status === 400) {
            // Expired or forged cursor: stop, remove the button and show a notice.
            if (more) more.remove();
            setApprovedMemoryStatus(deps.uiT("projects-more-stale"), "error");
            return;
          }
          if (!response.ok || !data || !Array.isArray(data.memories)) return;
          data.memories.forEach((memory) => {
            if (!memory || typeof memory.memory_id !== "string") return;
            clawApprovedList.appendChild(renderApprovedMemoryCard(memory));
          });
          const next = typeof data.next_cursor === "string" ? data.next_cursor : "";
          if (more && next) {
            more.dataset.cursor = next;
            more.disabled = false;
          } else if (more) {
            more.remove();
          }
        } finally {
          approvedMemoryInFlight = false;
        }
      }

      async function loadApprovedMemoryDetail(memoryId) {
        if (!clawApprovedMemory || approvedMemoryInFlight) return;
        approvedMemoryInFlight = true;
        setApprovedMemoryStatus("", "");
        if (clawApprovedLoading) clawApprovedLoading.hidden = false;
        if (clawApprovedList) clawApprovedList.hidden = true;
        if (clawApprovedEmpty) clawApprovedEmpty.hidden = true;
        try {
          const response = await fetch(`/api/claw/memory/${encodeURIComponent(memoryId)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
          const data = await response.json().catch(() => null);
          if (!response.ok || !data || !data.memory) {
            throw deps.mappedUiError(deps.approvedMemoryErrorMessage(data, response), data);
          }
          if (clawApprovedLoading) clawApprovedLoading.hidden = true;
          if (clawApprovedList) clawApprovedList.hidden = false;
          renderApprovedMemoryDetail(data.memory);
          // #4488 Phase A follow-up: a detail opened from inside the panel must be
          // visible (run-history focus parity — open the disclosure first).
          if (clawApprovedDisclosure) clawApprovedDisclosure.open = true;
        } catch (error) {
          if (clawApprovedLoading) clawApprovedLoading.hidden = true;
          setApprovedMemoryStatus(deps.safeLocalUiMessage(error, deps.clawT("claw-memory-error-generic")), "error", error?.code);
        } finally {
          approvedMemoryInFlight = false;
        }
      }

      function syncApprovedMemoryVisibility() {
        if (!clawApprovedMemory) return;
        // Owner-authenticated surface only: anonymous Phase A flow is unchanged.
        const onLanding = deps.clawWorkspace?.dataset.view === "general"
          && !deps.emptyState.hidden;
        const inActiveChat = deps.shell.dataset.state === "chat" && deps.emptyState.hidden;
        const show = deps.authState.authenticated === true
          && (deps.shell.dataset.state === "claw" || inActiveChat)
          && !onLanding;
        clawApprovedMemory.hidden = !show;
        if (clawApprovedDisclosure) clawApprovedDisclosure.hidden = !show;
        if (show) loadApprovedMemoryList();
      }

      // R5 A2 (rule (b)): registered from app.js at the original listener block.
      function wireMemoryListeners() {
        if (clawApprovedRefresh) {
          clawApprovedRefresh.addEventListener("click", () => loadApprovedMemoryList());
        }
      }

      // R5 A2 (rule (b)): exposes the window contract at the original app.js line.
      function wireMemoryReviewContract() {
        window.PadiemChatMemoryReview = Object.freeze({
          render: renderMemoryProposalReview,
          sync: () => {
            syncApprovedMemoryVisibility();
            deps.syncClawRunHistoryVisibility();
          },
        });
      }

      return {
        setApprovedMemoryStatus,
        renderMemoryProposalReview,
        proposalBody,
        approveProposal,
        rejectProposal,
        renderApprovedMemoryCard,
        renderApprovedMemoryDetail,
        fetchApprovedMemoryList,
        loadApprovedMemoryList,
        loadMoreApprovedMemories,
        loadApprovedMemoryDetail,
        syncApprovedMemoryVisibility,
        wireMemoryListeners,
        wireMemoryReviewContract,
      };
    },
  };
})();
