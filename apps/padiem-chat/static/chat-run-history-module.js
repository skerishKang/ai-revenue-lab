// R5 A2 - Claw run-history card renderer, runs-read short-window cache, and
// run-history panel controls moved out of the app.js closure under B1's four
// rules: (a) own cache state and button refs live inside create() without
// reading deps, (b) top-level listeners register from app.js at their original
// position, (c) shared state/DOM is accessed through the shared app context,
// (d) module API registers on app.provide.
(() => {
  "use strict";
  window.PadiemChatRunHistoryModule = {
    create(deps) {
      // The first screen reads /api/claw/runs twice: the sidebar needs the
      // run -> conversation mapping (limit 30) and Claw's history needs the run
      // cards (limit 10). The wider answer already contains the narrower one, so
      // one short-lived in-memory read answers both. It is keyed to the auth
      // generation and never stored outside memory; the window is short enough
      // that a run created just after it is seen on the next read.
      const CLAW_RUNS_READ_WINDOW_MS = 1500;
      const emptyClawRunsRead = () => ({
        at: 0, epoch: -1, limit: 0, response: null, data: null, inFlight: null, inFlightLimit: 0,
      });
      let clawRunsRead = emptyClawRunsRead();

      const clawRunHistoryRefresh = document.getElementById("clawRunHistoryRefresh");
      const clawRunHistoryFilter = document.getElementById("clawRunHistoryFilter");

      // A write that changes a run's status makes every answer in the window
      // stale, so the next read asks the server again.
      function invalidateClawRunsRead() {
        clawRunsRead = emptyClawRunsRead();
      }

      function readClawRuns(limit, epoch, options) {
        const force = Boolean(options && options.force === true);
        const now = Date.now();
        // An explicit refresh asks the server. A read already open still answers
        // it, so two rapid clicks stay one request.
        if (!force && clawRunsRead.epoch === epoch && clawRunsRead.data
            && clawRunsRead.limit >= limit
            && now - clawRunsRead.at < CLAW_RUNS_READ_WINDOW_MS) {
          return Promise.resolve({ response: clawRunsRead.response, data: clawRunsRead.data });
        }
        if (clawRunsRead.inFlight && clawRunsRead.epoch === epoch
            && clawRunsRead.inFlightLimit >= limit) {
          return clawRunsRead.inFlight;
        }
        const run = (async () => {
          const response = await fetch(`/api/claw/runs?limit=${limit}`, {
            headers: { "Accept": "application/json" }, cache: "no-store",
          });
          const data = await response.json().catch(() => null);
          if (response.ok && data && data.ok === true && Array.isArray(data.runs)) {
            clawRunsRead = { at: Date.now(), epoch, limit, response, data, inFlight: null, inFlightLimit: 0 };
          }
          return { response, data };
        })();
        clawRunsRead.epoch = epoch;
        clawRunsRead.inFlight = run;
        clawRunsRead.inFlightLimit = limit;
        run.finally(() => {
          if (clawRunsRead.inFlight === run) {
            clawRunsRead.inFlight = null;
            clawRunsRead.inFlightLimit = 0;
          }
        }).catch(() => {});
        return run;
      }

      // Unknown status tokens stay raw rather than being invented, so presentation
      // can never claim a completion the server did not report.
      function clawRunStatusLabel(status) {
        const raw = String(status || "");
        const key = `claw-runs-status-${raw}`;
        const text = deps.uiT(key);
        // Deliberately raw for an unknown run token: #3933 and the run-history UI
        // contract forbid the client deriving a run status, so an invented Korean
        // label here would be a second kind of untruth.
        return text === key ? raw : text;
      }

      function renderClawRunCard(run) {
        // L6: the meta line printed the raw ISO-8601 UTC instant the server stored
        // ("2026-09-19T01:00:00Z") straight at the reader. Show the same instant in
        // the page's own language and zone instead, and keep the exact stored value
        // in the element's title so nothing is hidden. A value the browser cannot
        // parse is shown exactly as the server sent it rather than as a guess.
        const instantLanguage = typeof document?.documentElement?.lang === "string"
          && document.documentElement.lang.toLowerCase().startsWith("en") ? "en" : "ko";
        const readableClawInstant = (value) => {
          if (typeof value !== "string" || !value) return "";
          const parsed = new Date(value);
          if (Number.isNaN(parsed.getTime())) return value;
          try {
            return new Intl.DateTimeFormat(instantLanguage, {
              dateStyle: "medium", timeStyle: "short",
            }).format(parsed);
          } catch (_) {
            return value;
          }
        };
        // L2 result-file card: the kind shown on a completed run's file is derived
        // ONLY from the server-verified media_type the owner-scoped run projection
        // already carries. A filename extension is never used to invent a type, and
        // an absent or unregistered media type renders no chip rather than a guess.
        // The map is closed, so a hostile media type can only fail to match.
        const artifactKindMap = Object.freeze({
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
          "application/vnd.ms-excel": "XLS",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
          "application/msword": "DOC",
          "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
          "application/pdf": "PDF",
          "text/csv": "CSV",
          "text/plain": "TXT",
          "application/zip": "ZIP",
          "image/png": "PNG",
          "image/jpeg": "JPG",
          "image/webp": "WEBP",
        });
        const artifactKindOf = (mediaType) => {
          if (typeof mediaType !== "string") return "";
          const normalized = mediaType.trim().toLowerCase();
          // Object prototype members such as "constructor" and "__proto__"
          // are not registered media types and must never produce a file chip.
          return Object.hasOwn(artifactKindMap, normalized) ? artifactKindMap[normalized] : "";
        };
        const card = document.createElement("div");
        card.className = "claw-run-card";
        card.dataset.runId = typeof run.run_id === "string" ? run.run_id : "";
        // Visual emphasis follows only the canonical server status. Unknown states
        // retain neutral styling and their raw label; they are never completed.
        const knownRunStates = ["completed", "waiting_approval", "failed", "cancelled"];
        if (knownRunStates.includes(run.status)) card.dataset.runState = run.status;

        const head = document.createElement("div");
        head.className = "claw-run-card-head";
        const title = document.createElement("strong");
        title.className = "claw-run-card-title";
        title.textContent = typeof run.title === "string" ? run.title : "";
        const badge = document.createElement("span");
        badge.className = "claw-run-card-badge";
        badge.textContent = clawRunStatusLabel(run.status);
        head.append(title, badge);

        const meta = document.createElement("div");
        meta.className = "claw-run-card-meta";
        const createdAt = typeof run.created_at === "string" ? run.created_at : "";
        meta.textContent = [run.channel, run.action, readableClawInstant(createdAt)]
          .map((value) => (typeof value === "string" ? value : ""))
          .filter(Boolean)
          .join(" · ");
        // The exact instant the server stored stays available even though the
        // visible text is localized, so nothing about the record is lost.
        if (createdAt) meta.setAttribute("title", createdAt);

        const summary = document.createElement("p");
        summary.className = "claw-run-card-summary";
        summary.textContent = typeof run.result_summary === "string" ? run.result_summary : "";

        card.append(head, meta, summary);
        if (["waiting_approval", "failed", "cancelled"].includes(run.status)) {
          const nextStep = document.createElement("p");
          nextStep.className = "claw-run-card-nextstep";
          nextStep.setAttribute("role", "note");
          nextStep.textContent = deps.clawT(`claw-runs-next-${run.status}`);
          card.appendChild(nextStep);
        }

        // Canonical session reopen (#2916): the action exists only when the server
        // projected a validated session handle. Created before the artifact block
        // (run-card static slice) and appended after it, so document action and
        // session action stay separate single-purpose controls that both reuse
        // existing owners instead of minting new authority.
        const sessionConversationId = run.session && typeof run.session.conversation_id === "string" && run.session.conversation_id
          ? run.session.conversation_id
          : null;
        let sessionBtn = null;
        if (sessionConversationId) {
          sessionBtn = document.createElement("button");
          sessionBtn.type = "button";
          sessionBtn.className = "claw-run-card-download claw-run-card-session";
          sessionBtn.textContent = deps.clawT("claw-runs-open-session");
          sessionBtn.addEventListener("click", () => {
            deps.openSavedConversation(sessionConversationId);
          });
        }

        const artifact = run.artifact && typeof run.artifact.document_id === "string" ? run.artifact : null;
        if (artifact) {
          const artifactRow = document.createElement("div");
          artifactRow.className = "claw-run-card-artifact";
          // L2: the file's own identity is grouped so a type chip can sit beside the
          // name. Grouping keeps the row's two-element shape (identity + one action)
          // and lets a long filename shrink instead of pushing the action out.
          const fileGroup = document.createElement("span");
          fileGroup.className = "claw-run-card-file";
          const artifactKind = artifactKindOf(artifact.media_type);
          if (artifactKind) {
            const kindChip = document.createElement("span");
            kindChip.className = "claw-run-card-kind";
            kindChip.textContent = artifactKind;
            kindChip.setAttribute("aria-label", deps.clawT("claw-runs-kind-aria", { kind: artifactKind }));
            fileGroup.appendChild(kindChip);
          }
          const filename = document.createElement("span");
          filename.className = "claw-run-card-filename";
          filename.textContent = typeof artifact.filename === "string" ? artifact.filename : "";
          fileGroup.appendChild(filename);
          const downloadBtn = document.createElement("button");
          downloadBtn.type = "button";
          downloadBtn.className = "claw-run-card-download";
          downloadBtn.textContent = deps.clawT("claw-runs-download");
          downloadBtn.addEventListener("click", () => {
            // Reuses the existing bounded artifact route through its single owner.
            if (artifact.document_id) deps.downloadClawArtifact(artifact.document_id, artifact.filename || "");
          });
          artifactRow.append(fileGroup, downloadBtn);
          // L2: one verified-preview decision, reused by the note and the controller.
          const previewable = Boolean(window.PadiemClawPdfPreview?.validHistoricalArtifact?.(artifact));
          // #3935: a history artifact reference does not make a failed, cancelled,
          // approval-paused or unknown run completed. Keep its original badge and
          // existing click-to-check download; never auto-retry or claim delivery.
          if (run.status !== "completed") {
            const caveat = document.createElement("p");
            caveat.className = "claw-run-card-partial-note";
            caveat.setAttribute("role", "note");
            caveat.textContent = deps.clawT("claw-runs-artifact-unverified");
            artifactRow.appendChild(caveat);
          }
          // L2: when no verified preview exists for this file, say so plainly so the
          // single download action is never read as a preview affordance.
          if (!previewable) {
            const downloadOnly = document.createElement("p");
            downloadOnly.className = "claw-run-card-download-only";
            downloadOnly.setAttribute("role", "note");
            downloadOnly.textContent = deps.clawT("claw-runs-download-only");
            fileGroup.appendChild(downloadOnly);
          }
          // #3932: old owner-scoped run receipts lack byte_length. Display a
          // truthful click-to-check PDF action, then use the existing authenticated
          // 10MiB PDF byte route. Never preview DOCX/XLSX or inferred filenames.
          if (previewable) {
            const viewer = window.PadiemClawPdfPreview.create({
              mount: artifactRow,
              onError: (message) => deps.setClawRunHistoryStatus(message),
            });
            if (viewer?.setHistorical?.(artifact)) deps.clawRunHistoryPdfControllers.add(viewer);
            else viewer?.destroy?.();
          }
          card.appendChild(artifactRow);
        }
        if (sessionBtn) card.appendChild(sessionBtn);
        if (run.status === "waiting_approval" && typeof run.run_id === "string" && run.run_id) {
          const approvalActions = document.createElement("div");
          approvalActions.className = "claw-approval-actions claw-run-approval-actions";
          approvalActions.setAttribute("role", "group");
          approvalActions.setAttribute("aria-label", deps.clawT("claw-approval-actions-aria"));
          deps.renderClawApprovalControls(approvalActions, run.run_id, async () => {
            await deps.loadClawRunHistory();
          });
          card.appendChild(approvalActions);
        }
        return card;
      }

      // R5 A2 (rule (b)): registered from app.js at the original listener block.
      function wireRunHistoryListeners() {
        if (clawRunHistoryFilter) {
          clawRunHistoryFilter.addEventListener("click", () => {
            const next = window.__padiemClawRunHistoryIncludeGeneral !== true;
            window.__padiemClawRunHistoryIncludeGeneral = next;
            clawRunHistoryFilter.dataset.runFilter = next ? "all" : "tools";
            clawRunHistoryFilter.setAttribute("aria-pressed", next ? "true" : "false");
            clawRunHistoryFilter.setAttribute("data-locale-key", next ? "claw-runs-filter-all" : "claw-runs-filter-tools");
            clawRunHistoryFilter.textContent = deps.uiT(next ? "claw-runs-filter-all" : "claw-runs-filter-tools");
            void deps.loadClawRunHistory({ force: true });
          });
        }
        if (clawRunHistoryRefresh) {
          // A person asked for the current list, so this read is not served from the
          // short window.
          clawRunHistoryRefresh.addEventListener("click", () => deps.loadClawRunHistory({ force: true }));
        }
        if (deps.clawRunHistoryExpand) {
          deps.clawRunHistoryExpand.addEventListener("click", () => {
            if (deps.clawRunHistoryInFlight || deps.clawRunHistoryLimit !== 10 ||
                deps.authState.authenticated !== true || deps.clawRunHistory.hidden) return;
            deps.clawRunHistoryLimit = 30;
            deps.clawRunHistoryExpand.hidden = true;
            void deps.loadClawRunHistory({ force: true });
          });
        }
      }

      return {
        invalidateClawRunsRead,
        readClawRuns,
        clawRunStatusLabel,
        renderClawRunCard,
        wireRunHistoryListeners,
      };
    },
  };
})();
