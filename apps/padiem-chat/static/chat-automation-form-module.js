// R5 A1 - automation edit/create form section moved out of the app.js closure.
// No behavior, copy, DOM id or event name change. Shared state and DOM refs are
// read/written only through the deps getters/setters. app.js keeps same-named
// one-line forwarders for the names the remaining app.js code still calls, and
// the rule-list module reaches these functions through the same forwarders.
(() => {
  "use strict";
  window.PadiemChatAutomationFormModule = {
    create(deps) {
    // --- #3257 Web Automation Create -------------------------------------------
    // Seven product fields only; the server rejects any authority field and owns
    // rule id, owner provenance, membership role and the execution target.
    let clawAutomationCreateInFlight = false;
    const clawAutomationCreate = document.getElementById("clawAutomationCreate");
    const clawAutomationCreateToggle = document.getElementById("clawAutomationCreateToggle");
    const clawAutomationCreateOpen = document.getElementById("clawAutomationCreateOpen");
    const clawAutomationCreateForm = document.getElementById("clawAutomationCreateForm");
    const clawAutomationCreateName = document.getElementById("clawAutomationCreateName");
    const clawAutomationCreateTask = document.getElementById("clawAutomationCreateTask");
    const clawAutomationCreateKind = document.getElementById("clawAutomationCreateKind");
    const clawAutomationCreateDaypartField = document.getElementById("clawAutomationCreateDaypartField");
    const clawAutomationCreateDaypart = document.getElementById("clawAutomationCreateDaypart");
    const clawAutomationCreateIntervalField = document.getElementById("clawAutomationCreateIntervalField");
    const clawAutomationCreateInterval = document.getElementById("clawAutomationCreateInterval");
    const clawAutomationCreateCronField = document.getElementById("clawAutomationCreateCronField");
    const clawAutomationCreateCron = document.getElementById("clawAutomationCreateCron");
    const clawAutomationCreateTimezone = document.getElementById("clawAutomationCreateTimezone");
    const clawAutomationCreateTarget = document.getElementById("clawAutomationCreateTarget");
    const clawAutomationCreateOutput = document.getElementById("clawAutomationCreateOutput");
    const clawAutomationCreateStatus = document.getElementById("clawAutomationCreateStatus");
    const clawAutomationCreateSubmit = document.getElementById("clawAutomationCreateSubmit");
    const clawAutomationCreateCancel = document.getElementById("clawAutomationCreateCancel");
    const clawAutomationEditForm = document.getElementById("clawAutomationEditForm");
    const clawAutomationEditName = document.getElementById("clawAutomationEditName");
    const clawAutomationEditKind = document.getElementById("clawAutomationEditKind");
    const clawAutomationEditDaypartField = document.getElementById("clawAutomationEditDaypartField");
    const clawAutomationEditDaypart = document.getElementById("clawAutomationEditDaypart");
    const clawAutomationEditIntervalField = document.getElementById("clawAutomationEditIntervalField");
    const clawAutomationEditInterval = document.getElementById("clawAutomationEditInterval");
    const clawAutomationEditCronField = document.getElementById("clawAutomationEditCronField");
    const clawAutomationEditCron = document.getElementById("clawAutomationEditCron");
    const clawAutomationEditTimezone = document.getElementById("clawAutomationEditTimezone");
    const clawAutomationEditStatus = document.getElementById("clawAutomationEditStatus");
    const clawAutomationEditSubmit = document.getElementById("clawAutomationEditSubmit");
    const clawAutomationEditCancel = document.getElementById("clawAutomationEditCancel");
    let clawAutomationEditingRuleId = null;
    let clawAutomationEditInFlight = false;
  // --- #3270 bounded edit (name + schedule only) -----------------------------
  // The form is prefilled ONLY from the existing safe projection, so the
  // browser never sees task/execution material. The PATCH carries exactly the
  // four editable fields; nothing is changed locally before the server answers
  // 200 and the canonical list is reloaded.
  function setClawAutomationEditStatus(messageKey) {
    if (!clawAutomationEditStatus) return;
    if (!messageKey) {
      clawAutomationEditStatus.hidden = true;
      clawAutomationEditStatus.textContent = "";
      return;
    }
    clawAutomationEditStatus.hidden = false;
    clawAutomationEditStatus.textContent = deps.uiT(messageKey);
  }

  function syncClawAutomationEditFields() {
    const kind = clawAutomationEditKind ? clawAutomationEditKind.value : "daypart";
    if (clawAutomationEditDaypartField) clawAutomationEditDaypartField.hidden = kind !== "daypart";
    if (clawAutomationEditIntervalField) clawAutomationEditIntervalField.hidden = kind !== "interval";
    if (clawAutomationEditCronField) clawAutomationEditCronField.hidden = kind !== "cron";
  }

  function clawAutomationEditExpression() {
    const kind = clawAutomationEditKind ? clawAutomationEditKind.value : "daypart";
    if (kind === "interval") return clawAutomationEditInterval ? clawAutomationEditInterval.value : "";
    if (kind === "cron") return clawAutomationEditCron ? clawAutomationEditCron.value : "";
    return clawAutomationEditDaypart ? clawAutomationEditDaypart.value : "";
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
    const button = findRuleEditButton(ruleId);
    if (button) {
      button.focus();
      return;
    }
    if (deps.clawAutomation) deps.clawAutomation.focus();
  }

  function openClawAutomationEdit(rule) {
    if (!clawAutomationEditForm) return;
    clawAutomationEditingRuleId = rule.rule_id;
    if (clawAutomationEditName) clawAutomationEditName.value = rule.name || "";
    if (clawAutomationEditKind) clawAutomationEditKind.value = rule.schedule_kind || "daypart";
    if (clawAutomationEditTimezone) clawAutomationEditTimezone.value = rule.schedule_timezone || "";
    // Prefill the kind-aware expression control from the projected schedule.
    const expression = rule.schedule_expression || "";
    if (rule.schedule_kind === "interval") {
      if (clawAutomationEditInterval) clawAutomationEditInterval.value = expression;
    } else if (rule.schedule_kind === "cron") {
      if (clawAutomationEditCron) clawAutomationEditCron.value = expression;
    } else if (clawAutomationEditDaypart) {
      clawAutomationEditDaypart.value = expression;
    }
    syncClawAutomationEditFields();
    setClawAutomationEditStatus(null);
    clawAutomationEditForm.hidden = false;
    if (clawAutomationEditName) clawAutomationEditName.focus();
  }

  function closeClawAutomationEdit() {
    const ruleId = clawAutomationEditingRuleId;
    clawAutomationEditingRuleId = null;
    if (clawAutomationEditForm) clawAutomationEditForm.hidden = true;
    if (ruleId) {
      const button = findRuleEditButton(ruleId);
      if (button) {
        button.focus();
        return;
      }
    }
    if (deps.clawAutomation) deps.clawAutomation.focus();
  }

  async function submitClawAutomationEdit(event) {
    event.preventDefault();
    const ruleId = clawAutomationEditingRuleId;
    if (!clawAutomationEditForm || clawAutomationEditInFlight || !ruleId) return;
    // Exactly the four editable fields — no authority or immutable field.
    const payload = {
      name: clawAutomationEditName ? clawAutomationEditName.value : "",
      schedule_kind: clawAutomationEditKind ? clawAutomationEditKind.value : "",
      schedule_expression: clawAutomationEditExpression(),
      schedule_timezone: clawAutomationEditTimezone ? clawAutomationEditTimezone.value : "",
    };
    clawAutomationEditInFlight = true;
    if (clawAutomationEditSubmit) clawAutomationEditSubmit.disabled = true;
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
        setClawAutomationEditStatus("claw-automation-edit-saved");
        await deps.loadClawAutomationRules();
        closeClawAutomationEdit();
        return;
      }
      const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
      if (response.status === 403 || code === "owner_role_required") {
        setClawAutomationEditStatus("claw-automation-toggle-forbidden");
      } else if (response.status === 404 || code === "automation_rule_not_found") {
        setClawAutomationEditStatus("claw-automation-toggle-not-found");
      } else if (code === "automation_rule_not_mutable") {
        setClawAutomationEditStatus("claw-automation-toggle-not-mutable");
      } else if (code === "automation_rule_not_execution_ready") {
        setClawAutomationEditStatus("claw-automation-toggle-not-ready");
      } else if (response.status === 400 || response.status === 413) {
        setClawAutomationEditStatus("claw-automation-edit-invalid");
      } else {
        setClawAutomationEditStatus("claw-automation-edit-failed");
      }
      // Failure: the form stays open with the entered values untouched and the
      // rendered rows unchanged — nothing is optimistically edited.
    } catch (_) {
      setClawAutomationEditStatus("claw-automation-edit-failed");
    } finally {
      clawAutomationEditInFlight = false;
      if (clawAutomationEditSubmit) clawAutomationEditSubmit.disabled = false;
    }
  }

  function setClawAutomationCreateStatus(messageKey) {
    if (!clawAutomationCreateStatus) return;
    if (!messageKey) {
      clawAutomationCreateStatus.hidden = true;
      clawAutomationCreateStatus.textContent = "";
      return;
    }
    clawAutomationCreateStatus.hidden = false;
    clawAutomationCreateStatus.textContent = deps.uiT(messageKey);
  }

  function syncClawAutomationCreateFields() {
    const kind = clawAutomationCreateKind ? clawAutomationCreateKind.value : "daypart";
    if (clawAutomationCreateDaypartField) clawAutomationCreateDaypartField.hidden = kind !== "daypart";
    if (clawAutomationCreateIntervalField) clawAutomationCreateIntervalField.hidden = kind !== "interval";
    if (clawAutomationCreateCronField) clawAutomationCreateCronField.hidden = kind !== "cron";
  }

  function clawAutomationCreateExpression() {
    const kind = clawAutomationCreateKind ? clawAutomationCreateKind.value : "daypart";
    if (kind === "interval") return clawAutomationCreateInterval ? clawAutomationCreateInterval.value : "";
    if (kind === "cron") return clawAutomationCreateCron ? clawAutomationCreateCron.value : "";
    return clawAutomationCreateDaypart ? clawAutomationCreateDaypart.value : "";
  }

  function resetClawAutomationCreateForm() {
    if (clawAutomationCreateForm) clawAutomationCreateForm.reset();
    syncClawAutomationCreateFields();
    setClawAutomationCreateStatus(null);
  }

  function closeClawAutomationCreate() {
    if (clawAutomationCreate && typeof clawAutomationCreate.open === "boolean") {
      clawAutomationCreate.open = false;
    }
    // The visible control is the header button, so the focus goes there.
    if (clawAutomationCreateOpen) clawAutomationCreateOpen.focus();
    else if (clawAutomationCreateToggle) clawAutomationCreateToggle.focus();
  }

  function scrollClawAutomationCreateIntoView() {
    // The narrow-window layout puts the rule list before the create form, so
    // opening the form has to bring it into view. A form that is already
    // visible stays where it is, and the wide-screen layout never moves.
    if (!clawAutomationCreate) return;
    const host = deps.clawAutomation.closest(".automation-view");
    if (!host) return;
    const form = clawAutomationCreate.getBoundingClientRect();
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
    if (!clawAutomationCreateForm || clawAutomationCreateInFlight) return;
    // The exact seven keys the server accepts — nothing else is ever sent, so
    // an authority field cannot leak into the payload through the form.
    const payload = {
      name: clawAutomationCreateName ? clawAutomationCreateName.value : "",
      task: clawAutomationCreateTask ? clawAutomationCreateTask.value : "",
      schedule_kind: clawAutomationCreateKind ? clawAutomationCreateKind.value : "",
      schedule_expression: clawAutomationCreateExpression(),
      schedule_timezone: clawAutomationCreateTimezone ? clawAutomationCreateTimezone.value : "",
      target_source: clawAutomationCreateTarget ? clawAutomationCreateTarget.value : "",
      output_type: clawAutomationCreateOutput ? clawAutomationCreateOutput.value : "",
    };
    clawAutomationCreateInFlight = true;
    if (clawAutomationCreateSubmit) clawAutomationCreateSubmit.disabled = true;
    setClawAutomationCreateStatus("claw-automation-create-saving");
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
        resetClawAutomationCreateForm();
        await deps.loadClawAutomationRules();
        closeClawAutomationCreate();
        return;
      }
      const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
      if (response.status === 401) {
        setClawAutomationCreateStatus("claw-automation-create-unauthorized");
      } else if (response.status === 403 || code === "owner_role_required") {
        // Bounded denial: never names or reveals another user's role/identity.
        setClawAutomationCreateStatus("claw-automation-create-forbidden");
      } else if (code === "automation_execution_target_unavailable") {
        // Truthful: nothing was saved; creation is not runtime-ready yet.
        setClawAutomationCreateStatus("claw-automation-create-runtime-unavailable");
      } else if (response.status === 400 || response.status === 413) {
        setClawAutomationCreateStatus("claw-automation-create-invalid");
      } else {
        setClawAutomationCreateStatus("claw-automation-create-failed");
      }
    } catch (_) {
      setClawAutomationCreateStatus("claw-automation-create-failed");
    } finally {
      clawAutomationCreateInFlight = false;
      if (clawAutomationCreateSubmit) clawAutomationCreateSubmit.disabled = false;
    }
  }


  // R5 B1 (rule (b)): the edit and create listeners register from app.js at
  // the original block positions; see automationForm.wireEditListeners() and
  // automationForm.wireCreateListeners().
  function wireEditListeners() {
    if (clawAutomationEditForm) {
      clawAutomationEditForm.addEventListener("submit", (event) => {
        void submitClawAutomationEdit(event);
      });
    }
    if (clawAutomationEditKind) {
      clawAutomationEditKind.addEventListener("change", syncClawAutomationEditFields);
    }
    if (clawAutomationEditCancel) {
      clawAutomationEditCancel.addEventListener("click", () => closeClawAutomationEdit());
    }
  }

  function wireCreateListeners() {
    if (clawAutomationCreateForm) {
      clawAutomationCreateForm.addEventListener("submit", (event) => {
        void submitClawAutomationCreate(event);
      });
    }
    if (clawAutomationCreateKind) {
      clawAutomationCreateKind.addEventListener("change", syncClawAutomationCreateFields);
    }
    if (clawAutomationCreateCancel) {
      clawAutomationCreateCancel.addEventListener("click", () => {
        resetClawAutomationCreateForm();
        closeClawAutomationCreate();
      });
    }
    if (clawAutomationCreate) {
      clawAutomationCreate.addEventListener("toggle", () => {
        // The header button owns the disclosure, so it carries the state.
        if (clawAutomationCreateOpen) {
          clawAutomationCreateOpen.setAttribute(
            "aria-expanded", clawAutomationCreate.open ? "true" : "false",
          );
        }
        if (clawAutomationCreate.open) {
          setClawAutomationCreateStatus(null);
          if (clawAutomationCreateName) clawAutomationCreateName.focus();
        } else if (clawAutomationCreateOpen) {
          clawAutomationCreateOpen.focus();
        }
      });
    }
    if (clawAutomationCreateOpen) {
      if (!clawAutomationCreate) {
        // No form to open, so the control is not offered at all.
        clawAutomationCreateOpen.hidden = true;
      } else {
        clawAutomationCreateOpen.addEventListener("click", () => {
          clawAutomationCreate.open = !clawAutomationCreate.open;
          // On a narrow window the form sits below the rule list, so the view
          // follows the user to it instead of leaving the input off-screen.
          if (clawAutomationCreate.open) {
            scrollClawAutomationCreateIntoView();
          }
        });
      }
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
        wireEditListeners,
        wireCreateListeners,
      };
    },
  };
})();
