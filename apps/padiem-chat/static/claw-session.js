(() => {
  "use strict";
  function bind({ noteApprovalSession, clearRecovery, clearWait }) {
    window.addEventListener("padiem:auth-state", (event) => {
      const session = window.PadiemAuthSession.get();
      const authenticated = session ? session.authenticated : event.detail.authenticated === true;
      noteApprovalSession(authenticated);
      if (authenticated) return;
      const automation = document.getElementById("clawAutomation");
      const automationList = document.getElementById("clawAutomationList");
      const workspace = document.getElementById("clawWorkspace");
      const runHistory = document.getElementById("clawRunHistory");
      const runHistoryList = document.getElementById("clawRunHistoryList");
      const runHistoryError = document.getElementById("clawRunHistoryError");
      // #3237: an Automation view never outlives the session that loaded it.
      if (automation) automation.hidden = true;
      if (automationList) automationList.replaceChildren();
      if (runHistory) runHistory.hidden = true;
      // #4488 Phase A follow-up: the approved-memory disclosure wrapper must
      // not outlive the session either (run-history parity).
      const approvedMemory = document.getElementById("clawApprovedMemory");
      const approvedDisclosure = document.getElementById("clawApprovedDisclosure");
      const approvedList = document.getElementById("clawApprovedList");
      const approvedError = document.getElementById("clawApprovedError");
      if (approvedMemory) approvedMemory.hidden = true;
      if (approvedDisclosure) {
        approvedDisclosure.hidden = true;
        approvedDisclosure.open = false;
      }
      if (approvedList) approvedList.replaceChildren();
      if (approvedError) {
        approvedError.hidden = true;
        approvedError.textContent = "";
        approvedError.removeAttribute("data-state");
      }
      // #4488 re-login: the pending approval decision surface is the one
      // session-scoped Claw control that carries a specific run_id together
      // with its approve/deny actions, so it must not outlive the session
      // either. Otherwise re-entering Claw after an auth loss would re-show a
      // previous session's decision controls for a run this session never
      // requested.
      const approvalActions = document.getElementById("clawApprovalActions");
      if (approvalActions) {
        approvalActions.replaceChildren();
        approvalActions.hidden = true;
      }
      // #4488 Phase A: the disclosure wrapper must not outlive the session.
      const runHistoryDisclosure = document.getElementById("clawRunHistoryDisclosure");
      if (runHistoryDisclosure) runHistoryDisclosure.hidden = true;
      if (runHistoryList) runHistoryList.replaceChildren();
      if (runHistoryError) {
        runHistoryError.hidden = true;
        runHistoryError.textContent = "";
        runHistoryError.removeAttribute("data-state");
      }
      if (workspace) {
        if (workspace.dataset.view === "automation") workspace.dataset.view = "general";
      }
      // Auth loss also closes PDF previews and revokes ephemeral private blobs.
      window.PadiemClawPdfPreview?.revokeAll?.();
      // Auth loss tears down any pending execute recovery: no timer outlives the session.
      clearRecovery({ syncControls: true });
      clearWait();
    });
  }
  window.PadiemClawSession = Object.freeze({ bind });
})();
