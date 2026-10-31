/* B66: one explicit new-template entry. Editing a quote is a different task.
   Hosts the existing approved Saved Skill workflows without cloning authority. */
(function () {
  "use strict";
  function byId(id) { return document.getElementById(id); }
  let dialog = null;
  let active = null;
  let watcher = null;
  let lastTrigger = null;
  let handingOff = false;

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
    if (!handingOff && lastTrigger && typeof lastTrigger.focus === "function") lastTrigger.focus();
    lastTrigger = null;
    handingOff = false;
  }

  function card(id, title, description, options) {
    const button = document.createElement("button");
    button.type = "button";
    button.id = id;
    const strong = document.createElement("strong");
    strong.textContent = title;
    const span = document.createElement("span");
    span.textContent = description;
    button.append(strong, span);
    if (options && options.disabled) {
      // Disabled, not hidden: the path exists in the product but does not work
      // yet, and saying "coming soon" would promise a date we do not have.
      button.disabled = true;
      button.setAttribute("aria-disabled", "true");
    }
    return button;
  }

  /* 파일/의뢰 화면은 자체 dialog 를 여는 B66 전용 모듈이 소유한다.
     시작 dialog 는 선택만 전달하고 닫힌 뒤 포커스를 되가져오지 않는다. */
  function handOff(handler) {
    if (typeof handler !== "function") return;
    handingOff = true;
    dialog.close();
    handler();
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
    const fromFile = card("b66SkillStartFromFile", "기존 파일에서 만들기 (지금은 사용할 수 없음)",
      "파일에서 양식 구조를 자동으로 읽는 기능은 아직 없습니다. 지금은 아래 두 가지로 만들 수 있습니다: 빈 양식 직접 만들기, 운영자에게 맡기기.",
      { disabled: true });
    const fromBlank = card("b66SkillStartFromBlank", "빈 양식 직접 만들기",
      "제목·표·회사정보·배치를 직접 구성합니다.");
    const fromAssist = card("b66SkillStartAssist", "운영자에게 맡기기",
      "회사 정보와 요청만 남기면 운영자가 검토해 내 견적서로 배정합니다.");
    choices.append(fromFile, fromBlank, fromAssist);
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
      const fromAssist = byId("b66SkillStartAssist");
      const safe = handlers || {};
      // The file path stays disabled: no automatic source extraction exists yet,
      // and opening the wizard would claim it does.
      fromFile.onclick = null;
      fromBlank.onclick = () => enter(byId("skillManualPanel"), safe.blankOpen, safe.blankCancel);
      fromAssist.onclick = () => handOff(safe.assistOpen);
      fromBlank.focus();
      return true;
    }
  });
})();
