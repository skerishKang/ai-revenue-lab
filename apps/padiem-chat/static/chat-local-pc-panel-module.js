// R5 B1 - the local PC "Connect this computer" handoff panel moved out of the
// app.js closure (rule (a)). Presentation only: it renders a projection some
// upstream authority already decided and holds none of the pairing/session/
// transport authority. No other zone calls this zone and it calls none; its
// listeners register from app.js at the original position (rule (b)) and the
// window contract keeps its original exposure timing inside wire().
(() => {
  "use strict";
  window.PadiemChatLocalPcPanelModule = {
    create(deps) {
    // ---------------------------------------------------------------------------
    // #3084 — Claw "Connect this computer" handoff panel.
    //
    // This is presentation only. It renders a projection that some upstream
    // authority already decided, and it holds none of the following:
    //   - pairing token minting/parsing/storage
    //   - a device-session store
    //   - a transport client (no fetch/WebSocket/polling to any broker)
    //   - task admission or approval decisions
    // The CTA therefore does NOT navigate or open a deep link here. It emits a
    // custom event carrying the opaque handoff value; the #3080 adapter (not yet
    // in this branch) is the only thing allowed to act on it.
    // ---------------------------------------------------------------------------
    const localHandoff = window.PadiemClawLocalHandoff;
    const localHandoffPanel = document.getElementById("clawLocalHandoff");
    const localHandoffRefs = localHandoffPanel
      ? {
          panel: localHandoffPanel,
          title: document.getElementById("clawLocalTitle"),
          body: document.getElementById("clawLocalBody"),
          state: document.getElementById("clawLocalState"),
          cta: document.getElementById("clawLocalCta"),
          installNote: document.getElementById("clawLocalInstallNote"),
          openNote: document.getElementById("clawLocalOpenNote"),
          identity: document.getElementById("clawLocalIdentity"),
          approval: document.getElementById("clawLocalApproval"),
          approvalTitle: document.getElementById("clawLocalApprovalTitle"),
          approvalBody: document.getElementById("clawLocalApprovalBody"),
          status: document.getElementById("clawLocalStatus"),
          statusTitle: document.getElementById("clawLocalStatusTitle"),
          statusBody: document.getElementById("clawLocalStatusBody"),
          result: document.getElementById("clawLocalResult"),
          resultTitle: document.getElementById("clawLocalResultTitle"),
          resultBody: document.getElementById("clawLocalResultBody"),
          evidence: document.getElementById("clawLocalEvidence"),
          evidenceTitle: document.getElementById("clawLocalEvidenceTitle"),
          evidenceList: document.getElementById("clawLocalEvidenceList"),
        }
      : null;
    const localHandoffCta = localHandoffRefs ? localHandoffRefs.cta : null;

    let localHandoffViewModel = null;

    function projectLocalHandoff(projection) {
      if (!localHandoff || !localHandoffRefs) return null;
      const model = localHandoff.deriveHandoffViewModel(projection || {});
      localHandoffViewModel = model;
      localHandoff.projectHandoffPanel(localHandoffRefs, model, window.__padiemLocale?.getCurrent?.() || "ko");
      return model;
    }


  // R5 B1 (rule (b)): called from app.js at the original region position,
  // so the two listener registrations and the window contract keep their
  // exact timing (the padiem:localechange order across the three zones is
  // preserved).
  function wire() {
    if (localHandoffCta) {
      localHandoffCta.addEventListener("click", () => {
        const model = localHandoffViewModel;
        // Never act unless the projection is genuinely usable. This is the
        // false-connected guard at the interaction layer, not just the view.
        if (!model || !model.canProceed) return;
        window.dispatchEvent(
          new CustomEvent("padiem:claw-local-connect-requested", {
            detail: {
              handoffValue: model.handoff.value,
              conversationId: model.identity.conversationId,
              runId: model.identity.runId,
              taskId: model.identity.taskId,
            },
          }),
        );
      });
    }

    // Re-render on locale change so KO/EN copy stays truthful.
    window.addEventListener("padiem:localechange", () => {
      if (!localHandoffViewModel || !localHandoffRefs) return;
      localHandoff.projectHandoffPanel(
        localHandoffRefs,
        localHandoffViewModel,
        window.__padiemLocale?.getCurrent?.() || "ko",
      );
    });
    window.__padiemClawLocalHandoff = Object.freeze({
      contractVersion: localHandoff?.CONTRACT_VERSION || null,
      project: projectLocalHandoff,
      getViewModel: () => localHandoffViewModel,
      fixtures: localHandoff?.FIXTURES || null,
      // #3094: the live conversation id, so the guarded adapter correlates the
      // projection it fetches with the conversation the user is actually in.
      // Read-only: this exposes no pairing, session or transport authority.
      getConversationId: () => window.PadiemChatConversationState?.getConversationId?.() || null,
    });
  }

      return {
        projectLocalHandoff,
        wire,
      };
    },
  };
})();
