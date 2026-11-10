// R5 A1 - automation section (rule list, read-only catalogue, toggle, view mount)
// moved out of the app.js closure. No behavior, copy, DOM id or event name
// change. Shared state and DOM refs are read/written only through the deps
// getters/setters. app.js keeps same-named one-line forwarders for the names
// the remaining app.js code still calls. Edit/create form functions live in
// chat-automation-form-module.js and are reached through the same forwarders.
(() => {
  "use strict";
  window.PadiemChatAutomationModule = {
    create(deps) {
      // #3237: canonical automation rule catalogue. #3257 adds the first Create
    // surface: the browser submits only the seven product fields, while rule id,
    // owner provenance, workspace/subject and the execution target (repository +
    // exact revision) are minted or derived server-side. Editing, deleting,
    // enabling/disabling and run-now remain out of scope.
    const automationNavButton = document.getElementById("automationNavButton");
    const clawAutomationLoading = document.getElementById("clawAutomationLoading");
    const clawAutomationError = document.getElementById("clawAutomationError");
    const clawAutomationForbidden = document.getElementById("clawAutomationForbidden");
    const clawAutomationEmpty = document.getElementById("clawAutomationEmpty");
    const clawAutomationRetry = document.getElementById("clawAutomationRetry");
    const clawAutomationToggleStatus = document.getElementById("clawAutomationToggleStatus");
    const clawAutomationInFlightRules = new Set();
    let automationViewMounted = false;
    // --- #3237 read-only automation rule catalogue -----------------------------
  function resetClawAutomationState() {
    if (clawAutomationLoading) clawAutomationLoading.hidden = true;
    if (clawAutomationError) clawAutomationError.hidden = true;
    if (clawAutomationForbidden) clawAutomationForbidden.hidden = true;
    if (clawAutomationEmpty) clawAutomationEmpty.hidden = true;
    // A retry belongs to a failed load. It is never a permanent control.
    setClawAutomationRetryVisible(false);
  }

  function setClawAutomationLoading() {
    resetClawAutomationState();
    if (deps.clawAutomationList) deps.clawAutomationList.replaceChildren();
    if (clawAutomationLoading) {
      clawAutomationLoading.hidden = false;
      clawAutomationLoading.textContent = deps.uiT("claw-automation-loading");
    }
  }

  function setClawAutomationError() {
    resetClawAutomationState();
    if (deps.clawAutomationList) deps.clawAutomationList.replaceChildren();
    if (clawAutomationError) {
      clawAutomationError.hidden = false;
      clawAutomationError.textContent = deps.uiT("claw-automation-error");
    }
    // The load failed, so the one action that can change the outcome is
    // offered here and nowhere else.
    setClawAutomationRetryVisible(true);
  }

  function setClawAutomationForbidden() {
    // A permission refusal is not a transient failure. It says what it is
    // instead of claiming the rules could not be loaded, and it offers no
    // retry, because a retry would not change the answer.
    resetClawAutomationState();
    if (deps.clawAutomationList) deps.clawAutomationList.replaceChildren();
    if (clawAutomationForbidden) {
      clawAutomationForbidden.hidden = false;
      clawAutomationForbidden.textContent = deps.uiT("claw-automation-forbidden");
    }
  }

  function renderClawAutomationRules(rules) {
    if (!deps.clawAutomationList) return;
    deps.clawAutomationList.replaceChildren();
    if (!rules.length) {
      if (clawAutomationEmpty) {
        clawAutomationEmpty.hidden = false;
        clawAutomationEmpty.textContent = deps.uiT("claw-automation-empty");
      }
      return;
    }
    rules.forEach((rule) => {
      const row = document.createElement("div");
      row.className = "claw-inbox-card";
      row.dataset.ruleId = rule.rule_id;
      const title = document.createElement("strong");
      // Server-projected metadata goes through a text sink only.
      title.textContent = rule.name;
      const meta = document.createElement("small");
      const schedule = `${rule.schedule_expression} (${rule.schedule_timezone})`;
      // "Rule setting" wording, never a bare on/off that could be read as
      // "automatic execution is live" — #2833 is still HOLD for Production
      // scheduler activation.
      meta.textContent = [
        `${deps.uiT("automation-rule-setting")}: ${rule.enabled ? deps.uiT("automation-rule-on") : deps.uiT("automation-rule-off")}`,
        schedule,
        rule.target_source,
        rule.output_type,
      ].join(" · ");
      row.append(title, meta);
      // #3043: a legacy rule is quarantined — it can never run in the
      // background — so the row must say so rather than look like a live rule.
      if (rule.background_eligible !== true || rule.authority_status !== "canonical") {
        row.dataset.ruleAuthority = "legacy_quarantined";
        const notice = document.createElement("small");
        notice.className = "claw-automation-quarantine";
        notice.dataset.localeKey = "automation-rule-quarantined";
        notice.textContent = deps.uiT("automation-rule-quarantined");
        row.appendChild(notice);
      } else {
        // #3262: only canonical, background-eligible rows carry the toggle.
        // The action reflects the STORED setting only — turning a rule on is
        // not automatic execution going live (#2833 scheduler HOLD).
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "claw-automation-rule-toggle";
        toggle.dataset.ruleToggleRuleId = rule.rule_id;
        toggle.dataset.localeKey = rule.enabled === true ? "claw-automation-rule-turn-off" : "claw-automation-rule-turn-on";
        toggle.textContent = deps.uiT(toggle.dataset.localeKey);
        toggle.addEventListener("click", () => {
          void toggleClawAutomationRule(rule.rule_id, rule.enabled !== true, toggle);
        });
        row.appendChild(toggle);
        // #3270: Edit is offered on the same eligible rows only, and edits
        // name + schedule exclusively (never task/execution material).
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "claw-automation-rule-edit";
        edit.dataset.ruleEditRuleId = rule.rule_id;
        edit.dataset.localeKey = "claw-automation-edit-button";
        edit.textContent = deps.uiT("claw-automation-edit-button");
        edit.addEventListener("click", () => {
          deps.openClawAutomationEdit(rule);
        });
        row.appendChild(edit);
      }
      deps.clawAutomationList.appendChild(row);
    });
  }

  async function loadClawAutomationRules() {
    if (!deps.clawAutomation || !deps.authState.authenticated) return;
    const signedOutNote = document.getElementById("automationViewSignedOut");
    if (signedOutNote) signedOutNote.hidden = true;
    setClawAutomationLoading();
    try {
      const response = await fetch("/api/claw/automation/rules", {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      const code = data && typeof data.code === "string" ? data.code : "";
      if (response.status === 403 || code === "owner_role_required") {
        setClawAutomationForbidden();
        return;
      }
      if (!response.ok || !data || data.ok !== true || !Array.isArray(data.rules)) {
        throw new Error("automation rules unavailable");
      }
      resetClawAutomationState();
      renderClawAutomationRules(data.rules);
    } catch (_) {
      setClawAutomationError();
    }
  }

  // --- #3262 owner-gated enable/disable -------------------------------------
  // The stored rule setting only: turning a rule on is NOT automatic execution
  // going live. No optimistic flip — the row is never changed locally; the
  // canonical list is reloaded after the server answers 200.
  function setClawAutomationToggleStatus(messageKey) {
    if (!clawAutomationToggleStatus) return;
    if (!messageKey) {
      clawAutomationToggleStatus.hidden = true;
      clawAutomationToggleStatus.textContent = "";
      return;
    }
    clawAutomationToggleStatus.hidden = false;
    clawAutomationToggleStatus.textContent = deps.uiT(messageKey);
  }

  function findRuleToggleButton(ruleId) {
    if (!deps.clawAutomationList) return null;
    for (const row of deps.clawAutomationList.children) {
      for (const node of row.children || []) {
        if (node.dataset && node.dataset.ruleToggleRuleId === ruleId) return node;
      }
    }
    return null;
  }

  function focusRuleToggleAfterReload(ruleId) {
    const button = findRuleToggleButton(ruleId);
    if (button) {
      button.focus();
      return;
    }
    if (deps.clawAutomation) deps.clawAutomation.focus();
  }

  async function toggleClawAutomationRule(ruleId, nextEnabled, button) {
    if (!ruleId || clawAutomationInFlightRules.has(ruleId)) return;
    clawAutomationInFlightRules.add(ruleId);
    if (button) button.disabled = true;
    try {
      const response = await fetch(
        `/api/claw/automation/rules/${encodeURIComponent(ruleId)}/enabled`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          // The exact two-part payload: the boolean setting, nothing else.
          body: JSON.stringify({ enabled: nextEnabled }),
        },
      );
      const data = await response.json().catch(() => null);
      if (response.status === 200 && data && data.ok === true) {
        setClawAutomationToggleStatus("claw-automation-toggle-saved");
        await loadClawAutomationRules();
        focusRuleToggleAfterReload(ruleId);
        return;
      }
      const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
      if (response.status === 403 || code === "owner_role_required") {
        setClawAutomationToggleStatus("claw-automation-toggle-forbidden");
      } else if (response.status === 404 || code === "automation_rule_not_found") {
        setClawAutomationToggleStatus("claw-automation-toggle-not-found");
      } else if (code === "automation_rule_not_mutable") {
        setClawAutomationToggleStatus("claw-automation-toggle-not-mutable");
      } else if (code === "automation_rule_not_execution_ready") {
        setClawAutomationToggleStatus("claw-automation-toggle-not-ready");
      } else if (response.status === 400 || response.status === 413) {
        setClawAutomationToggleStatus("claw-automation-toggle-invalid");
      } else {
        setClawAutomationToggleStatus("claw-automation-toggle-failed");
      }
    } catch (_) {
      setClawAutomationToggleStatus("claw-automation-toggle-failed");
    } finally {
      clawAutomationInFlightRules.delete(ruleId);
      if (button) button.disabled = false;
    }
  }

  function mountAutomationView() {
    if (automationViewMounted) return;
    let body = null;
    let panel = null;
    try {
      body = document.getElementById("automationViewBody");
      panel = document.getElementById("clawAutomation");
    } catch (_) {
      return;
    }
    if (!body || !panel) return;
    body.appendChild(panel);
    // The page header owns the visible title on this surface, so the section
    // takes its accessible name from there instead of from the heading the
    // page already shows.
    const pageTitle = document.getElementById("automationViewTitle");
    if (pageTitle) panel.setAttribute("aria-labelledby", "automationViewTitle");
    automationViewMounted = true;
  }

  function openClawAutomation() {
    if (!deps.clawWorkspace || !deps.clawAutomation) return;
    mountAutomationView();
    const view = document.getElementById("automationView");
    if (view) view.hidden = false;
    deps.shell.dataset.state = "automation";
    deps.clearClawWait();
    // Leaving the Claw workspace hides the run panel, exactly as the inbox
    // view switch used to; returning refetches through the sync below.
    deps.syncClawRunHistoryVisibility();
    deps.setNavActive();
    deps.closeSidebar();
    // Owner decision: every screen stays browsable without a session. The page
    // opens for a visitor, but the rule list is still never requested — the
    // server owns the tenant, and the signed-out note replaces the rows.
    const signedOut = document.getElementById("automationViewSignedOut");
    if (!deps.authState.authenticated) {
      deps.clawAutomation.hidden = true;
      if (signedOut) signedOut.hidden = false;
      return;
    }
    if (signedOut) signedOut.hidden = true;
    deps.clawAutomation.hidden = false;
    loadClawAutomationRules();
  }

  // The retry is a failure-only control. It lives here, next to the loader
  // it retries, and it is never part of the permanent header.
  function setClawAutomationRetryVisible(visible) {
    if (clawAutomationRetry) clawAutomationRetry.hidden = !visible;
  }


  // R5 B1 (rule (b)): the view listeners register from app.js at the
  // original block position; see automation.wireViewListeners().
  function wireViewListeners() {
    if (automationNavButton) automationNavButton.addEventListener("click", openClawAutomation);
    // #4462: automation-related run/completion/failure alerts stay reachable
    // from the automation view after the standalone sidebar Alerts entry is gone.
    if (clawAutomationRetry) clawAutomationRetry.addEventListener("click", () => void loadClawAutomationRules());
  }

      return {
        resetClawAutomationState,
        setClawAutomationLoading,
        setClawAutomationError,
        setClawAutomationForbidden,
        renderClawAutomationRules,
        loadClawAutomationRules,
        setClawAutomationToggleStatus,
        findRuleToggleButton,
        focusRuleToggleAfterReload,
        toggleClawAutomationRule,
        mountAutomationView,
        openClawAutomation,
        setClawAutomationRetryVisible,
        wireViewListeners,
      };
    },
  };
})();
