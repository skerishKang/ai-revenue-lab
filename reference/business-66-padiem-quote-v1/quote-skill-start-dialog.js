/* B66: one explicit new-template entry. Editing a quote is a different task.
   Hosts the existing approved Saved Skill workflows without cloning authority. */
(function () {
  "use strict";
  function byId(id) { return document.getElementById(id); }
  let dialog = null;
  let active = null;
  let watcher = null;
  let lastTrigger = null;

  function restore() {
    if (watcher) { watcher.disconnect(); watcher = null; }
    if (active) {
      const current = active;
      active = null;
      if (!current.panel.hidden) current.cancel();
      current.anchor.replaceWith(current.panel);
    }
    if (dialog) {
      dialog.querySelector(".b66-skill-start-choices").hidden = false;
      dialog.querySelector(".b66-skill-start-hint").hidden = false;
    }
    if (lastTrigger && typeof lastTrigger.focus === "function") lastTrigger.focus();
    lastTrigger = null;
  }

  function init() {
    if (dialog) return;
    dialog = document.createElement("dialog");
    dialog.id = "b66SkillStartDialog";
    dialog.className = "b66-skill-start-dialog";
    dialog.setAttribute("aria-labelledby", "b66SkillStartTitle");
    const heading = document.createElement("div");
    heading.className = "b66-skill-start-heading";
    const title = document.createElement("h2");
    title.id = "b66SkillStartTitle";
    title.textContent = "새 견적서 양식 만들기";
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "닫기";
    close.setAttribute("aria-label", "양식 만들기 닫기");
    close.addEventListener("click", () => dialog.close());
    heading.append(title, close);
    const hint = document.createElement("p");
    hint.className = "b66-skill-start-hint";
    hint.textContent = "견적 금액 입력과 달리, 앞으로 반복 사용할 견적서 모양을 등록합니다. 저장·적용은 기존 승인 절차를 따릅니다.";
    const choices = document.createElement("div");
    choices.className = "b66-skill-start-choices";
    const fromFile = document.createElement("button");
    fromFile.type = "button";
    fromFile.id = "b66SkillStartFromFile";
    fromFile.innerHTML = "<strong>기존 파일에서 만들기</strong><span>PDF·엑셀·사진 등의 견적서를 선택하고 검토합니다.</span>";
    const fromBlank = document.createElement("button");
    fromBlank.type = "button";
    fromBlank.id = "b66SkillStartFromBlank";
    fromBlank.innerHTML = "<strong>빈 양식 직접 만들기</strong><span>제목·표·회사정보·배치를 직접 구성합니다.</span>";
    choices.append(fromFile, fromBlank);
    dialog.append(heading, hint, choices);
    document.body.appendChild(dialog);
    dialog.addEventListener("close", restore);
  }

  function enter(panel, openPanel, cancelPanel) {
    if (!dialog || !panel || active) return;
    const anchor = document.createComment("b66-skill-original-position");
    panel.parentNode.insertBefore(anchor, panel);
    dialog.appendChild(panel);
    active = { panel: panel, anchor: anchor, cancel: cancelPanel };
    dialog.querySelector(".b66-skill-start-choices").hidden = true;
    dialog.querySelector(".b66-skill-start-hint").hidden = true;
    watcher = new MutationObserver(() => {
      if (active && active.panel === panel && panel.hidden && dialog.open) {
        dialog.close();
      }
    });
    watcher.observe(panel, { attributes: true, attributeFilter: ["hidden"] });
    try {
      openPanel();
    } catch (error) {
      dialog.close();
      throw error;
    }
  }

  window.B66SkillStartDialog = Object.freeze({
    open: function (handlers, trigger) {
      init();
      if (dialog.open) dialog.close();
      lastTrigger = trigger || null;
      dialog.showModal();
      const fromFile = byId("b66SkillStartFromFile");
      const fromBlank = byId("b66SkillStartFromBlank");
      fromFile.onclick = () => enter(byId("skillWizardPanel"), handlers.fileOpen, handlers.fileCancel);
      fromBlank.onclick = () => enter(byId("skillManualPanel"), handlers.blankOpen, handlers.blankCancel);
      fromFile.focus();
      return true;
    }
  });
})();
