(function () {
  "use strict";

  var PROJECT_NUMBER_ALIASES = {
    "lovebud": 23,
    "lovetree-3": 24,
    "love-matchmaking": 25,
    "portfolio-console": 44
  };

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  function language() {
    return document.documentElement.lang === "en" ? "en" : "ko";
  }

  function businesses() {
    return Array.isArray(window.ARL_BUSINESSES) ? window.ARL_BUSINESSES : [];
  }

  function applyProjectNumberAliases() {
    if (!Array.isArray(window.ARL_PROJECTS)) return;
    window.ARL_PROJECTS.forEach(function (project) {
      if (Object.prototype.hasOwnProperty.call(PROJECT_NUMBER_ALIASES, project.id)) {
        project.businessNumber = PROJECT_NUMBER_ALIASES[project.id];
      }
    });
  }

  function businessForRow(row) {
    if (!row) return null;
    var number = Number(row.dataset.bizNumber);
    return businesses().find(function (business) {
      return business.number === number;
    }) || null;
  }

  function isExpandedSuccessor(business) {
    return Boolean(business && business.portfolioClass === "expanded-successor");
  }

  function isNonWebSurface(business) {
    return Boolean(
      business &&
      business.reviewSurface &&
      business.reviewSurface.kind === "cli-tui"
    );
  }

  function isWebSurface(business) {
    if (!business || isNonWebSurface(business) || isExpandedSuccessor(business)) return false;
    return /^https:\/\//.test(String(business.surfaceUrl || ""));
  }

  function openBusinessSurface(business) {
    if (!isWebSurface(business)) return false;
    window.open(business.surfaceUrl, "_blank", "noopener,noreferrer");
    return true;
  }

  function expandedCopy(business) {
    var successor = language() === "en"
      ? (business.successorTitle || "successor")
      : (business.successorKoreanTitle || business.successorTitle || "후속 프로젝트");
    if (language() === "en") {
      return {
        authority: "EXPANDED",
        lineage: "Expanded to " + successor + " · external development",
        action: successor + " ↗",
        aria: "B" + pad(business.number) + " " + business.title + " expanded to " + successor,
        dialogAuthority: "EXPANDED · number lineage B" + pad(business.number) + " retained",
        dialogPhase: "Expanded to " + successor + " · internal UI/UX/BE phases do not apply",
        dialogLifecycle: "expanded successor · " + successor
      };
    }
    return {
      authority: "확장",
      lineage: successor + "으로 확장 · 외부 개발",
      action: successor + " ↗",
      aria: "B" + pad(business.number) + " " + business.title + " " + successor + "으로 확장",
      dialogAuthority: "확장 · B" + pad(business.number) + " 번호 계보 유지",
      dialogPhase: successor + "으로 확장 · 내부 UI/UX/BE 단계 미적용",
      dialogLifecycle: "확장 후속 · " + successor
    };
  }

  function launcherCopy(counts) {
    if (language() === "en") {
      return [
        '<strong>Business Launcher</strong>',
        '<span class="launcher-count launcher-count-web">Open ' + counts.web + '</span>',
        '<span class="launcher-count">Non-web ' + counts.nonWeb + '</span>',
        '<span class="launcher-count launcher-count-expanded">Expanded ' + counts.expanded + '</span>',
        '<span class="launcher-count">Undeployed ' + counts.missing + '</span>',
        '<span class="launcher-hint">Row click = open site · Details = status</span>'
      ];
    }
    return [
      '<strong>Business Launcher</strong>',
      '<span class="launcher-count launcher-count-web">바로 열기 ' + counts.web + '</span>',
      '<span class="launcher-count">비웹 ' + counts.nonWeb + '</span>',
      '<span class="launcher-count launcher-count-expanded">확장 ' + counts.expanded + '</span>',
      '<span class="launcher-count">미배포 ' + counts.missing + '</span>',
      '<span class="launcher-hint">행 클릭 = 사이트 열기 · 상세 = 상태 확인</span>'
    ];
  }

  function ensureSummary() {
    var view = document.querySelector("#view-business");
    var controls = document.querySelector("#view-business .business-controls");
    if (!view || !controls) return null;

    var summary = document.querySelector("#business-launcher-summary");
    if (!summary) {
      summary = document.createElement("div");
      summary.id = "business-launcher-summary";
      summary.className = "business-launcher-summary";
      controls.parentNode.insertBefore(summary, controls);
    }

    var counts = businesses().reduce(function (acc, business) {
      if (isWebSurface(business)) acc.web += 1;
      else if (isNonWebSurface(business)) acc.nonWeb += 1;
      else if (isExpandedSuccessor(business)) acc.expanded += 1;
      else acc.missing += 1;
      return acc;
    }, { web: 0, nonWeb: 0, expanded: 0, missing: 0 });

    var next = launcherCopy(counts).join("");
    if (summary.innerHTML !== next) summary.innerHTML = next;
    return summary;
  }

  function stripPhasePrefix(text) {
    return String(text || "").replace(/^(UI|UX|BE)\s*·\s*/, "").trim();
  }

  function decoratePhaseBadges(row, business) {
    if (!row || !business || isExpandedSuccessor(business)) return;
    var badges = row.querySelectorAll(".biz-phase-badge");
    var prefixes = ["UI", "UX", "BE"];
    var statuses = [business.uiStatus, business.uxStatus, business.backendStatus];
    badges.forEach(function (badge, index) {
      var value = stripPhasePrefix(badge.textContent);
      if (statuses[index] === "BLOCKED_BY_UI") {
        value = language() === "en" ? "WAIT FOR UI" : "UI 확정 대기";
      }
      var next = prefixes[index] + " · " + value;
      if (badge.textContent !== next) badge.textContent = next;
      badge.dataset.phase = prefixes[index].toLowerCase();
    });
  }

  function decorateExpandedRow(row, business) {
    if (!row || !business || !isExpandedSuccessor(business)) return;
    var copy = expandedCopy(business);
    row.classList.add("is-expanded-successor");
    row.dataset.portfolioClass = "expanded-successor";
    row.setAttribute("aria-label", copy.aria);

    var authority = row.querySelector(".biz-auth");
    if (authority) {
      authority.classList.add("biz-auth-expanded");
      authority.title = language() === "en"
        ? "Current classification: expanded successor · number authority retained separately"
        : "현재 분류: 확장 후속 · 번호 권한은 별도 유지";
      if (authority.textContent !== copy.authority) authority.textContent = copy.authority;
    }

    var phaseGroup = row.querySelector(".biz-phase-group");
    if (phaseGroup) {
      phaseGroup.classList.add("is-expanded-lineage");
      var lineage = phaseGroup.querySelector(".biz-expanded-lineage");
      if (!lineage) {
        phaseGroup.textContent = "";
        lineage = document.createElement("span");
        lineage.className = "biz-expanded-lineage";
        phaseGroup.appendChild(lineage);
      }
      if (lineage.textContent !== copy.lineage) lineage.textContent = copy.lineage;
    }
  }

  function decorateExpandedDialog(business) {
    if (!isExpandedSuccessor(business)) return;
    var dialog = document.querySelector("#business-dialog");
    var body = document.querySelector("#biz-dialog-body");
    if (!dialog || !dialog.open || !body) return;
    var number = body.querySelector(".dialog-biznumber");
    if (!number || number.textContent.trim() !== "B" + pad(business.number)) return;

    var copy = expandedCopy(business);
    var sections = body.querySelectorAll(".dialog-section");
    if (sections[0]) {
      var authorityValue = sections[0].querySelector(".dialog-section-value");
      if (authorityValue && authorityValue.textContent !== copy.dialogAuthority) {
        authorityValue.textContent = copy.dialogAuthority;
      }
    }
    if (sections[1]) {
      var phaseValue = sections[1].querySelector(".dialog-section-value");
      if (phaseValue && phaseValue.textContent !== copy.dialogPhase) {
        phaseValue.textContent = copy.dialogPhase;
      }
    }
    if (sections[2]) {
      var lifecycleValue = sections[2].querySelector(".dialog-section-value");
      if (lifecycleValue && lifecycleValue.textContent !== copy.dialogLifecycle) {
        lifecycleValue.textContent = copy.dialogLifecycle;
      }
    }

    var links = body.querySelector(".dialog-links");
    if (links && business.successorRepository && !links.querySelector(".expanded-successor-link")) {
      var external = document.createElement("a");
      external.className = "dialog-link expanded-successor-link";
      external.href = business.successorRepository;
      external.target = "_blank";
      external.rel = "noopener noreferrer";
      external.textContent = copy.action;
      links.appendChild(external);
    }
  }

  function syncLanguageUI() {
    var lang = language();
    var headerPrefix = document.querySelector("#header-prefix");
    if (headerPrefix) {
      headerPrefix.textContent = headerPrefix.getAttribute("data-prefix-" + lang) || headerPrefix.textContent;
    }
    ensureSummary();
    document.querySelectorAll("#biz-list .biz-item").forEach(function (row) {
      enhanceRow(row);
    });

    var blockedOptions = document.querySelectorAll('#biz-ui-filter option[value="BLOCKED_BY_UI"], #biz-ux-filter option[value="BLOCKED_BY_UI"]');
    blockedOptions.forEach(function (option) {
      var next = lang === "en" ? "WAIT FOR UI" : "UI 확정 대기";
      if (option.textContent !== next) option.textContent = next;
    });

    var openDialogNumber = document.querySelector("#biz-dialog-body .dialog-biznumber");
    if (openDialogNumber) {
      var match = /^B(\d+)$/.exec(openDialogNumber.textContent.trim());
      if (match) {
        var business = businesses().find(function (item) { return item.number === Number(match[1]); });
        if (business) decorateExpandedDialog(business);
      }
    }
  }

  function dispatchDetail(row) {
    if (!row) return;
    row.dataset.launcherDetailBypass = "1";
    try {
      row.dispatchEvent(new MouseEvent("click", {
        bubbles: true,
        cancelable: true,
        view: window
      }));
    } finally {
      delete row.dataset.launcherDetailBypass;
    }
  }

  function enhanceRow(row) {
    if (!row) return;
    var business = businessForRow(row);
    if (!business) return;

    var web = isWebSurface(business);
    var nonWeb = isNonWebSurface(business);
    var expanded = isExpandedSuccessor(business);
    var lang = language();

    if (expanded) decorateExpandedRow(row, business);
    else decoratePhaseBadges(row, business);

    row.classList.toggle("has-direct-service", web);
    row.dataset.launchMode = web ? "web" : expanded ? "expanded" : nonWeb ? "non-web" : "detail";
    if (!expanded) {
      row.setAttribute(
        "aria-label",
        "B" + pad(business.number) + " " + business.title + (web ? (lang === "en" ? " open site" : " 사이트 열기") : (lang === "en" ? " details" : " 상세 보기"))
      );
    }

    var existingActions = row.querySelector(".biz-launch-actions");
    if (existingActions) {
      var existingOpen = existingActions.querySelector(".biz-launch-open");
      var existingExternal = existingActions.querySelector(".biz-launch-external");
      var existingState = existingActions.querySelector(".biz-launch-state");
      var existingDetail = existingActions.querySelector(".biz-launch-detail");
      if (existingOpen) existingOpen.textContent = lang === "en" ? "Open site ↗" : "사이트 열기 ↗";
      if (existingExternal && expanded) existingExternal.textContent = expandedCopy(business).action;
      if (existingState && !nonWeb && !expanded) existingState.textContent = lang === "en" ? "Undeployed" : "미배포";
      if (existingDetail) existingDetail.textContent = lang === "en" ? "Details" : "상세";
      return;
    }

    var actions = document.createElement("div");
    actions.className = "biz-launch-actions";

    if (web) {
      var open = document.createElement("a");
      open.className = "biz-launch-open";
      open.href = business.surfaceUrl;
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      open.textContent = lang === "en" ? "Open site ↗" : "사이트 열기 ↗";
      open.setAttribute("aria-label", "B" + pad(business.number) + " " + business.title + (lang === "en" ? " open site" : " 사이트 열기"));
      open.addEventListener("click", function (event) {
        event.stopPropagation();
      });
      actions.appendChild(open);
    } else if (expanded && business.successorRepository) {
      var successorLink = document.createElement("a");
      successorLink.className = "biz-launch-external";
      successorLink.href = business.successorRepository;
      successorLink.target = "_blank";
      successorLink.rel = "noopener noreferrer";
      successorLink.textContent = expandedCopy(business).action;
      successorLink.setAttribute("aria-label", expandedCopy(business).aria);
      successorLink.addEventListener("click", function (event) {
        event.stopPropagation();
      });
      actions.appendChild(successorLink);
    } else {
      var state = document.createElement("span");
      state.className = "biz-launch-state";
      state.textContent = nonWeb ? "CLI/TUI" : (lang === "en" ? "Undeployed" : "미배포");
      actions.appendChild(state);
    }

    var detail = document.createElement("button");
    detail.type = "button";
    detail.className = "biz-launch-detail";
    detail.textContent = lang === "en" ? "Details" : "상세";
    detail.setAttribute("aria-label", "B" + pad(business.number) + " " + business.title + (lang === "en" ? " details" : " 상세 보기"));
    detail.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      dispatchDetail(row);
      decorateExpandedDialog(business);
    });
    actions.appendChild(detail);

    row.appendChild(actions);
  }

  function enhanceRows() {
    ensureSummary();
    document.querySelectorAll("#biz-list .biz-item").forEach(enhanceRow);
  }

  function switchToLauncherView() {
    var button = document.querySelector('.view-nav-item[data-view="business"]');
    if (button && !button.classList.contains("is-active")) {
      button.click();
    }
    enhanceRows();
  }

  document.addEventListener("click", function (event) {
    var row = event.target && event.target.closest ? event.target.closest(".biz-item") : null;
    if (!row || row.dataset.launcherDetailBypass === "1") return;
    if (event.target.closest(".biz-launch-actions")) return;

    var business = businessForRow(row);
    if (!isWebSurface(business)) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    openBusinessSurface(business);
  }, true);

  document.addEventListener("click", function (event) {
    var langButton = event.target && event.target.closest ? event.target.closest(".lang-btn") : null;
    if (!langButton) return;
    window.setTimeout(syncLanguageUI, 0);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var row = event.target && event.target.closest ? event.target.closest(".biz-item") : null;
    if (!row || event.target.closest(".biz-launch-actions")) return;

    var business = businessForRow(row);
    if (!isWebSurface(business)) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    openBusinessSurface(business);
  }, true);

  function init() {
    applyProjectNumberAliases();
    var list = document.querySelector("#biz-list");
    if (list) {
      new MutationObserver(function () {
        enhanceRows();
      }).observe(list, { childList: true });
    }
    syncLanguageUI();
    window.setTimeout(switchToLauncherView, 0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();