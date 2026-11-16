// #7216 R5 A10 — screen switching (nav): the PAGE_VIEWS projection, the URL
// fragment rules, setNavActive, the Chat|Claw conversation product switch and
// the Claw/Chat workspace entries. Moved verbatim from app.js. R5 part 2 B2-4:
// the declarations only this module uses (page contract, route-fragment table,
// Claw navigation entry) live here too, so app.js keeps only the shared route
// fragments, the two window contracts (PadiemChatRouting, PadiemAppSwitch),
// one-line forwarders and wire calls at the original listener positions.
(() => {
  "use strict";

  window.PadiemChatNavModule = {
    create(deps) {
      /* R5 part 2 B2-4: the route-fragment table, the page contract table and
         the Claw navigation entry are used only by this module, so they are
         declared here. The fragment table is built from the shared route
         fragments on first use — create() itself never reads deps — and keeps
         the frozen shape app.js published before. */
      let panelRouteHashByState = null;
      let ownedPanelHashes = null;
      function panelRouteHashes() {
        if (!panelRouteHashByState) {
          panelRouteHashByState = Object.freeze({
            calendar: deps.CALENDAR_ROUTE_HASH,
            library: deps.LIBRARY_ROUTE_HASH,
            meeting: deps.MEETING_ROUTE_HASH,
            settings: deps.ADVANCED_SETTINGS_ROUTE_HASH,
          });
          ownedPanelHashes = new Set(Object.values(panelRouteHashByState));
        }
        return panelRouteHashByState;
      }
      function ownedPanelHashSet() {
        panelRouteHashes();
        return ownedPanelHashes;
      }
      // One page contract for every shell screen. This table is the only place a
      // screen names itself, says which dedicated panel it owns, lists the
      // sub-views that show the shared hero and marks its navigation entry; the
      // shell publishes `data-page-id` and `data-layout-variant` from it and the
      // shared stylesheet selects on those two attributes. A new page therefore
      // adds one entry here and reuses the Chat/Claw geometry instead of declaring
      // a second set of product rules. It moves existing conditions into data and
      // does not change which element is shown or hidden.
      const PAGE_VIEWS = Object.freeze([
        Object.freeze({ pageId: "home", navigationId: "newChatButton", layoutVariant: "conversation", panelId: null, heroViews: null }),
        Object.freeze({ pageId: "chat", navigationId: "newChatButton", layoutVariant: "conversation", panelId: null, heroViews: null }),
        Object.freeze({ pageId: "claw", navigationId: "clawNavButton", layoutVariant: "workspace", panelId: "clawWorkspace", heroViews: Object.freeze(["general"]) }),
        Object.freeze({ pageId: "connectors", navigationId: "connectorsNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
        Object.freeze({ pageId: "automation", navigationId: "automationNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
        Object.freeze({ pageId: "meeting", navigationId: "meetingNavButton", layoutVariant: "panel", panelId: "meetingView", heroViews: null }),
        Object.freeze({ pageId: "calendar", navigationId: "calendarNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
        Object.freeze({ pageId: "library", navigationId: "filesNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
        Object.freeze({ pageId: "settings", navigationId: "settingsButton", layoutVariant: "panel", panelId: null, heroViews: null }),
        Object.freeze({ pageId: "util", navigationId: "utilNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
      ]);
      const PAGE_VIEW_BY_ID = Object.freeze(
        PAGE_VIEWS.reduce((index, view) => Object.assign(index, { [view.pageId]: view }), {})
      );
      const clawNavButton = document.getElementById("clawNavButton");
      function pageViewFor(state) {
        return PAGE_VIEW_BY_ID[state] || PAGE_VIEW_BY_ID.home;
      }
      function syncRouteHash() {
        // 11-03 audit: every panel screen names itself in the URL. Calendar and
        // Library change the shell state from their own modules, so they ask for
        // this instead of repeating the fragment: the table below stays the only
        // place a screen names its own destination. A fragment this shell does not
        // own is left alone, exactly like the three routes above.
        if (!deps.automationDestinationReady || !window.history || !window.location) return;
        const state = deps.shell.dataset.state;
        const desired = panelRouteHashes()[state] || "";
        const currentHash = String(window.location.hash || "");
        if (currentHash === desired) return;
        const basePath = window.location.pathname + window.location.search;
        if (desired) {
          window.history.replaceState(window.history.state, "", basePath + desired);
        } else if (ownedPanelHashSet().has(currentHash)) {
          window.history.replaceState(window.history.state, "", basePath);
        }
      }
      function setNavActive() {
        const state = deps.shell.dataset.state;
        const page = pageViewFor(state);
        // The URL fragment is the destination bookmark; no browser persistence.
        if (deps.automationDestinationReady && window.history && window.location) {
          const currentHash = String(window.location.hash || "");
          const isAutomationRoute = currentHash === deps.AUTOMATION_ROUTE_HASH;
          const isClawRoute = currentHash === deps.CLAW_ROUTE_HASH;
          const isConnectorsRoute = currentHash === deps.CONNECTORS_ROUTE_HASH;
          const basePath = window.location.pathname + window.location.search;
          if (state === "automation" && !isAutomationRoute) {
            window.history.replaceState(window.history.state, "", basePath + deps.AUTOMATION_ROUTE_HASH);
          } else if (state === "claw" && !isClawRoute) {
            window.history.replaceState(window.history.state, "", basePath + deps.CLAW_ROUTE_HASH);
          } else if (state === "connectors" && !isConnectorsRoute) {
            window.history.replaceState(window.history.state, "", basePath + deps.CONNECTORS_ROUTE_HASH);
          } else if (state !== "automation" && isAutomationRoute) {
            window.history.replaceState(window.history.state, "", basePath);
          } else if (state !== "claw" && isClawRoute) {
            window.history.replaceState(window.history.state, "", basePath);
          } else if (state !== "connectors" && isConnectorsRoute) {
            window.history.replaceState(window.history.state, "", basePath);
          }
        }
        // The three panel screens above own their fragment through the same rule,
        // so this runs after them and only touches the fragments it names.
        syncRouteHash();
        const workspace = document.getElementById("clawWorkspace");
        const view = workspace ? String(workspace.dataset.view || "") : "";
        // The contract attribute the shared stylesheet selects on. Claw keeps one
        // conversation surface and changes only its working panel, so the hero
        // geometry follows the sub-views the entry lists instead of a product rule.
        const conversationHero = page.layoutVariant === "conversation" ||
          (Array.isArray(page.heroViews) && page.heroViews.includes(view));
        deps.shell.dataset.pageId = page.pageId;
        deps.shell.dataset.layoutVariant = conversationHero ? "conversation" : page.layoutVariant;
        PAGE_VIEWS.forEach((entry) => {
          if (!entry.panelId) return;
          const panel = document.getElementById(entry.panelId);
          if (panel) panel.hidden = entry.panelId !== page.panelId;
        });
        const modeBar = document.getElementById("clawManualForm");
        if (modeBar) modeBar.hidden = !(page.pageId === "claw" && view === "manual");
        // #3531: the explicit manual-entry control lives in the fixed composer
        // wrap and shows only on the general Claw view — never by default
        // elsewhere, never inside the manual form it opens.
        const entryBar = document.getElementById("clawManualEntryBar");
        if (entryBar) entryBar.hidden = !(page.pageId === "claw" && page.heroViews.includes(view));
        deps.syncComposerForClaw(state === "claw");
        const chatNav = document.getElementById("newChatButton");
        const clawNav = document.getElementById("clawNavButton");
            // New Chat no longer shows a mode hint: the redundant label was removed
        // when the sidebar actions row was rearranged (B62 split-search task).
        if (clawNav) clawNav.dataset.modeHint = deps.uiT("nav-claw-hint");
        // 11-03 audit: Calendar and Library own their menu row now, so the entry
        // stops claiming those two screens as well — otherwise two rows read as
        // current at once.
        if (chatNav) chatNav.setAttribute("aria-current", (state === "claw" || state === "connectors" || state === "automation" || state === "meeting" || state === "util") ? "false" : "page");
        if (chatNav && (state === "calendar" || state === "library")) chatNav.setAttribute("aria-current", "false");
        if (clawNav) clawNav.setAttribute("aria-current", state === "claw" ? "page" : "false");
        const utilNav = document.getElementById("utilNavButton");
        if (utilNav) utilNav.setAttribute("aria-current", state === "util" ? "page" : "false");
        const meetingNav = document.getElementById("meetingNavButton");
        if (meetingNav) meetingNav.setAttribute("aria-current", state === "meeting" ? "page" : "false");
        const connectorsNav = document.getElementById("connectorsNavButton");
        if (connectorsNav) connectorsNav.setAttribute("aria-current", state === "connectors" ? "page" : "false");
        const automationNav = document.getElementById("automationNavButton");
        if (automationNav) automationNav.setAttribute("aria-current", state === "automation" ? "page" : "false");
          }
      // #2505: Chat and Claw show the SAME conversation. Opening the other screen
      // changes the lane the next submit belongs to, and keeps the transcript, the
      // conversation id and the stored record exactly as they are — so a thread
      // started on one screen continues on the other.
      function switchConversationProduct(nextProduct) {
        const target = nextProduct === deps.PRODUCT_CLAW ? deps.PRODUCT_CLAW : deps.PRODUCT_CHAT;
        if (deps.conversationProduct === target) return;
        deps.conversationState.setProduct?.(target);
        deps.conversationProduct = target;
        const hasTurns = deps.messageList.children.length > 0;
        deps.messageList.hidden = !hasTurns;
        deps.emptyState.hidden = hasTurns;
        // The Claw artifact index belongs to the Claw conversation only.
        if (target === deps.PRODUCT_CLAW) {
          const clawConversationId = deps.conversationState.getConversationId(deps.PRODUCT_CLAW);
          if (clawConversationId && deps.clawArtifactShownFor !== clawConversationId) {
            deps.clawArtifactShownFor = clawConversationId;
            deps.conversationArtifactContext?.show?.(clawConversationId);
          }
        } else {
          deps.clawArtifactShownFor = "";
          deps.conversationArtifactContext?.clear?.();
        }
      }
      function openClawWorkspace() {
        // #3531: Claw opens on the general conversation view. The document
        // workflow (manual form, workflow chrome) stays hidden until the user
        // explicitly enters it via openClawManual.
        if (!deps.clawWorkspace) return;
        deps.shell.dataset.state = "claw";
        // #2505: entering Claw selects the Claw lane and keeps the same conversation,
        // so the thread continues instead of restarting.
        switchConversationProduct(deps.PRODUCT_CLAW);
        deps.clawWorkspace.dataset.view = "general";
        // The shared Chat first-use hero also introduces Claw when the
        // existing conversation has not started. Do not reset live messages.
        if (deps.messageList.hidden && deps.messageList.children.length === 0) deps.emptyState.hidden = false;
        if (deps.app.clawAutomation) deps.app.clawAutomation.hidden = true;
        if (deps.clawManualForm) deps.clawManualForm.hidden = true;
        if (deps.clawResultArea) deps.clawResultArea.hidden = false;
        setNavActive();
        deps.input.focus();
        deps.closeSidebar();
        deps.app.syncApprovedMemoryVisibility();
        deps.syncClawRunHistoryVisibility();
      }

      function openChatWorkspace() {
        // #7173: back to the Chat lane on the same conversation (#2505); the Util
        // screen owns its own state and hash, and hides itself before this runs.
        deps.shell.dataset.state = "home";
        switchConversationProduct(deps.PRODUCT_CHAT);
        setNavActive();
        if (deps.input) deps.input.focus();
        deps.closeSidebar();
      }

      function openClawManual() {
        // Explicit entry into the document/quotation workflow only. The manual
        // form and its workflow chrome are never shown by default.
        if (!deps.clawWorkspace) return;
        deps.shell.dataset.state = "claw";
        // Chat/Claw separation: the document workflow belongs to the Claw conversation.
        switchConversationProduct(deps.PRODUCT_CLAW);
        deps.clawWorkspace.dataset.view = "manual";
        if (deps.app.clawAutomation) deps.app.clawAutomation.hidden = true;
        if (deps.clawManualForm) deps.clawManualForm.hidden = false;
        if (deps.clawResultArea) deps.clawResultArea.hidden = false;
        setNavActive();
        deps.input.focus();
        deps.closeSidebar();
        deps.app.syncApprovedMemoryVisibility();
        deps.syncClawRunHistoryVisibility();
      }

      function openClawRunTarget(runId) {
        deps.pendingClawRunFocusId = runId;
        openClawWorkspace();
      }


      // Registered by app.js at the original padiem:calendar-open-link block
      // position so the registration order is preserved.
      function wireNavRouteListener() {
      window.addEventListener("padiem:calendar-open-link", (event) => {
        const detail = event && event.detail && typeof event.detail === "object" ? event.detail : {};
        const kind = typeof detail.kind === "string" ? detail.kind : "";
        const targetId = typeof detail.targetId === "string" ? detail.targetId : "";
        if (kind === "claw_session" && /^chat_[0-9a-f]{32}$/.test(targetId)) {
          void deps.openSavedConversation(targetId);
          return;
        }
            if (kind === "run" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(targetId)) {
          openClawRunTarget(targetId);
          return;
        }
        if (kind === "artifact" && /^doc_[A-Za-z0-9]{32}$/.test(targetId)) {
          openClawWorkspace();
          void deps.downloadClawArtifact(targetId, "");
        }
      });

      }

      // Registered by app.js at the original Claw entry listener block
      // position (clawNavButton, padiem:meeting-open, clawManualEntryButton).
      function wireNavEntryListeners() {
      if (clawNavButton) clawNavButton.addEventListener("click", openClawWorkspace);
      // #4647 Same central workbench for menu entry and Claw natural language.
      window.addEventListener("padiem:meeting-open", () => {
        if (!deps.authState.authenticated) return;
        deps.shell.dataset.state = "meeting";
        setNavActive();
        deps.closeSidebar();
      });
      const clawManualEntryButton = document.getElementById("clawManualEntryButton");
      if (clawManualEntryButton) clawManualEntryButton.addEventListener("click", openClawManual);
      }

      return {
        pageViewFor,
        syncRouteHash,
        setNavActive,
        switchConversationProduct,
        openClawWorkspace,
        openChatWorkspace,
        openClawManual,
        openClawRunTarget,
        wireNavRouteListener,
        wireNavEntryListeners,
      };
    },
  };
})();
