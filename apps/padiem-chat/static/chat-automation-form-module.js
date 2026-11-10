// R5 A1 - automation edit/create form section moved out of the app.js closure.
// No behavior, copy, DOM id or event name change. Shared state and DOM refs are
// read/written only through the deps getters/setters. app.js keeps same-named
// one-line forwarders for the names the remaining app.js code still calls, and
// the rule-list module reaches these functions through the same forwarders.
(() => {
  "use strict";
  window.PadiemChatAutomationFormModule = {
    create(deps) {
  // --- #3270 bounded edit (name + schedule only) -----------------------------
  // The form is prefilled ONLY from the existing safe projection, so the
  // browser never sees task/execution material. The PATCH carries exactly the
  // four editable fields; nothing is changed locally before the server answers
  // 200 and the canonical list is reloaded.
  function setClawAutomationEditStatus(messageKey) {
    if (!deps.clawAutomationEditStatus) return;
    if (!messageKey) {
      deps.clawAutomationEditStatus.hidden = true;
      deps.clawAutomationEditStatus.textContent = "";
      return;
    }
    deps.clawAutomationEditStatus.hidden = false;
    deps.clawAutomationEditStatus.textContent = deps.uiT(messageKey);
  }

  function syncClawAutomationEditFields() {
    const kind = deps.clawAutomationEditKind ? deps.clawAutomationEditKind.value : "daypart";
    if (deps.clawAutomationEditDaypartField) deps.clawAutomationEditDaypartField.hidden = kind !== "daypart";
    if (deps.clawAutomationEditIntervalField) deps.clawAutomationEditIntervalField.hidden = kind !== "interval";
    if (deps.clawAutomationEditCronField) deps.clawAutomationEditCronField.hidden = kind !== "cron";
  }

  function clawAutomationEditExpression() {
    const kind = deps.clawAutomationEditKind ? deps.clawAutomationEditKind.value : "daypart";
    if (kind === "interval") return deps.clawAutomationEditInterval ? deps.clawAutomationEditInterval.value : "";
    if (kind === "cron") return deps.clawAutomationEditCron ? deps.clawAutomationEditCron.value : "";
    return deps.clawAutomationEditDaypart ? deps.clawAutomationEditDaypart.value : "";
  }

  function findRuleEditButton(ruleId) {
    if (!deps.clawAutomationList) return null;
    for (const row of deps.clawAutomationList.children) {
      for (const node of row.children || []) {
        if (node.dataset && node.dataset.ruleEditRuleId === ruleId) return node;
      }
    }
    return null;
  }

  function focusRuleEditAfterReload(ruleId) {
    const button = deps.findRuleEditButton(ruleId);
    if (button) {
      button.focus();
      return;
    }
    if (deps.clawAutomation) deps.clawAutomation.focus();
  }

  function openClawAutomationEdit(rule) {
    if (!deps.clawAutomationEditForm) return;
    deps.clawAutomationEditingRuleId = rule.rule_id;
    if (deps.clawAutomationEditName) deps.clawAutomationEditName.value = rule.name || "";
    if (deps.clawAutomationEditKind) deps.clawAutomationEditKind.value = rule.schedule_kind || "daypart";
    if (deps.clawAutomationEditTimezone) deps.clawAutomationEditTimezone.value = rule.schedule_timezone || "";
    // Prefill the kind-aware expression control from the projected schedule.
    const expression = rule.schedule_expression || "";
    if (rule.schedule_kind === "interval") {
      if (deps.clawAutomationEditInterval) deps.clawAutomationEditInterval.value = expression;
    } else if (rule.schedule_kind === "cron") {
      if (deps.clawAutomationEditCron) deps.clawAutomationEditCron.value = expression;
    } else if (deps.clawAutomationEditDaypart) {
      deps.clawAutomationEditDaypart.value = expression;
    }
    deps.syncClawAutomationEditFields();
    deps.setClawAutomationEditStatus(null);
    deps.clawAutomationEditForm.hidden = false;
    if (deps.clawAutomationEditName) deps.clawAutomationEditName.focus();
  }

  function closeClawAutomationEdit() {
    const ruleId = deps.clawAutomationEditingRuleId;
    deps.clawAutomationEditingRuleId = null;
    if (deps.clawAutomationEditForm) deps.clawAutomationEditForm.hidden = true;
    if (ruleId) {
      const button = deps.findRuleEditButton(ruleId);
      if (button) {
        button.focus();
        return;
      }
    }
    if (deps.clawAutomation) deps.clawAutomation.focus();
  }

  async function submitClawAutomationEdit(event) {
    event.preventDefault();
    const ruleId = deps.clawAutomationEditingRuleId;
    if (!deps.clawAutomationEditForm || deps.clawAutomationEditInFlight || !ruleId) return;
    // Exactly the four editable fields — no authority or immutable field.
    const payload = {
      name: deps.clawAutomationEditName ? deps.clawAutomationEditName.value : "",
      schedule_kind: deps.clawAutomationEditKind ? deps.clawAutomationEditKind.value : "",
      schedule_expression: deps.clawAutomationEditExpression(),
      schedule_timezone: deps.clawAutomationEditTimezone ? deps.clawAutomationEditTimezone.value : "",
    };
    deps.clawAutomationEditInFlight = true;
    if (deps.clawAutomationEditSubmit) deps.clawAutomationEditSubmit.disabled = true;
    try {
      const response = await fetch(
        `/api/claw/automation/rules/${encodeURIComponent(ruleId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const data = await response.json().catch(() => null);
      if (response.status === 200 && data && data.ok === true) {
        deps.setClawAutomationEditStatus("claw-automation-edit-saved");
        await deps.loadClawAutomationRules();
        deps.closeClawAutomationEdit();
        return;
      }
      const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
      if (response.status === 403 || code === "owner_role_required") {
        deps.setClawAutomationEditStatus("claw-automation-toggle-forbidden");
      } else if (response.status === 404 || code === "automation_rule_not_found") {
        deps.setClawAutomationEditStatus("claw-automation-toggle-not-found");
      } else if (code === "automation_rule_not_mutable") {
        deps.setClawAutomationEditStatus("claw-automation-toggle-not-mutable");
      } else if (code === "automation_rule_not_execution_ready") {
        deps.setClawAutomationEditStatus("claw-automation-toggle-not-ready");
      } else if (response.status === 400 || response.status === 413) {
        deps.setClawAutomationEditStatus("claw-automation-edit-invalid");
      } else {
        deps.setClawAutomationEditStatus("claw-automation-edit-failed");
      }
      // Failure: the form stays open with the entered values untouched and the
      // rendered rows unchanged — nothing is optimistically edited.
    } catch (_) {
      deps.setClawAutomationEditStatus("claw-automation-edit-failed");
    } finally {
      deps.clawAutomationEditInFlight = false;
      if (deps.clawAutomationEditSubmit) deps.clawAutomationEditSubmit.disabled = false;
    }
  }

  function setClawAutomationCreateStatus(messageKey) {
    if (!deps.clawAutomationCreateStatus) return;
    if (!messageKey) {
      deps.clawAutomationCreateStatus.hidden = true;
      deps.clawAutomationCreateStatus.textContent = "";
      return;
    }
    deps.clawAutomationCreateStatus.hidden = false;
    deps.clawAutomationCreateStatus.textContent = deps.uiT(messageKey);
  }

  function syncClawAutomationCreateFields() {
    const kind = deps.clawAutomationCreateKind ? deps.clawAutomationCreateKind.value : "daypart";
    if (deps.clawAutomationCreateDaypartField) deps.clawAutomationCreateDaypartField.hidden = kind !== "daypart";
    if (deps.clawAutomationCreateIntervalField) deps.clawAutomationCreateIntervalField.hidden = kind !== "interval";
    if (deps.clawAutomationCreateCronField) deps.clawAutomationCreateCronField.hidden = kind !== "cron";
  }

  function clawAutomationCreateExpression() {
    const kind = deps.clawAutomationCreateKind ? deps.clawAutomationCreateKind.value : "daypart";
    if (kind === "interval") return deps.clawAutomationCreateInterval ? deps.clawAutomationCreateInterval.value : "";
    if (kind === "cron") return deps.clawAutomationCreateCron ? deps.clawAutomationCreateCron.value : "";
    return deps.clawAutomationCreateDaypart ? deps.clawAutomationCreateDaypart.value : "";
  }

  function resetClawAutomationCreateForm() {
    if (deps.clawAutomationCreateForm) deps.clawAutomationCreateForm.reset();
    deps.syncClawAutomationCreateFields();
    deps.setClawAutomationCreateStatus(null);
  }

  function closeClawAutomationCreate() {
    if (deps.clawAutomationCreate && typeof deps.clawAutomationCreate.open === "boolean") {
      deps.clawAutomationCreate.open = false;
    }
    // The visible control is the header button, so the focus goes there.
    if (deps.clawAutomationCreateOpen) deps.clawAutomationCreateOpen.focus();
    else if (deps.clawAutomationCreateToggle) deps.clawAutomationCreateToggle.focus();
  }

  function scrollClawAutomationCreateIntoView() {
    // The narrow-window layout puts the rule list before the create form, so
    // opening the form has to bring it into view. A form that is already
    // visible stays where it is, and the wide-screen layout never moves.
    if (!deps.clawAutomationCreate) return;
    const host = deps.clawAutomation.closest(".automation-view");
    if (!host) return;
    const form = deps.clawAutomationCreate.getBoundingClientRect();
    const area = host.getBoundingClientRect();
    // A form whose top is already on screen stays where it is: the view only
    // moves when the form would otherwise open below the fold.
    if (form.top >= area.top && form.top < area.bottom) return;
    const target = Math.max(0, host.scrollTop + (form.top - area.top) - 8);
    // The scroll is applied directly: the list re-renders behind the form, and
    // an animated scroll would be cancelled by that reflow.
    host.scrollTop = target;
  }

  async function submitClawAutomationCreate(event) {
    event.preventDefault();
    if (!deps.clawAutomationCreateForm || deps.clawAutomationCreateInFlight) return;
    // The exact seven keys the server accepts — nothing else is ever sent, so
    // an authority field cannot leak into the payload through the form.
    const payload = {
      name: deps.clawAutomationCreateName ? deps.clawAutomationCreateName.value : "",
      task: deps.clawAutomationCreateTask ? deps.clawAutomationCreateTask.value : "",
      schedule_kind: deps.clawAutomationCreateKind ? deps.clawAutomationCreateKind.value : "",
      schedule_expression: deps.clawAutomationCreateExpression(),
      schedule_timezone: deps.clawAutomationCreateTimezone ? deps.clawAutomationCreateTimezone.value : "",
      target_source: deps.clawAutomationCreateTarget ? deps.clawAutomationCreateTarget.value : "",
      output_type: deps.clawAutomationCreateOutput ? deps.clawAutomationCreateOutput.value : "",
    };
    deps.clawAutomationCreateInFlight = true;
    if (deps.clawAutomationCreateSubmit) deps.clawAutomationCreateSubmit.disabled = true;
    deps.setClawAutomationCreateStatus("claw-automation-create-saving");
    try {
      const response = await fetch("/api/claw/automation/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => null);
      if (response.status === 201 && data && data.ok === true && data.rule) {
        // Success is the reloaded canonical list; no optimistic fake row is
        // ever inserted locally.
        deps.resetClawAutomationCreateForm();
        await deps.loadClawAutomationRules();
        deps.closeClawAutomationCreate();
        return;
      }
      const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
      if (response.status === 401) {
        deps.setClawAutomationCreateStatus("claw-automation-create-unauthorized");
      } else if (response.status === 403 || code === "owner_role_required") {
        // Bounded denial: never names or reveals another user's role/identity.
        deps.setClawAutomationCreateStatus("claw-automation-create-forbidden");
      } else if (code === "automation_execution_target_unavailable") {
        // Truthful: nothing was saved; creation is not runtime-ready yet.
        deps.setClawAutomationCreateStatus("claw-automation-create-runtime-unavailable");
      } else if (response.status === 400 || response.status === 413) {
        deps.setClawAutomationCreateStatus("claw-automation-create-invalid");
      } else {
        deps.setClawAutomationCreateStatus("claw-automation-create-failed");
      }
    } catch (_) {
      deps.setClawAutomationCreateStatus("claw-automation-create-failed");
    } finally {
      deps.clawAutomationCreateInFlight = false;
      if (deps.clawAutomationCreateSubmit) deps.clawAutomationCreateSubmit.disabled = false;
    }
  }

      return {
        setClawAutomationEditStatus,
        syncClawAutomationEditFields,
        clawAutomationEditExpression,
        findRuleEditButton,
        focusRuleEditAfterReload,
        openClawAutomationEdit,
        closeClawAutomationEdit,
        submitClawAutomationEdit,
        setClawAutomationCreateStatus,
        syncClawAutomationCreateFields,
        clawAutomationCreateExpression,
        resetClawAutomationCreateForm,
        closeClawAutomationCreate,
        scrollClawAutomationCreateIntoView,
        submitClawAutomationCreate,
      };
    },
  };
})();
