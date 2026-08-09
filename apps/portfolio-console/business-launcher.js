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

  function isNonWebSurface(business) {
    return Boolean(
      business &&
      business.reviewSurface &&
      business.reviewSurface.kind === "cli-tui"
    );
  }

  function isWebSurface(business) {
    if (!business || isNonWebSurface(business)) return false;
    return /^https:\/\//.test(String(business.surfaceUrl || ""));
  }

  function openBusinessSurface(business) {
    if (!isWebSurface(business)) return false;
    window.open(business.surfaceUrl, "_blank", "noopener,noreferrer");
    return true;
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
      else acc.missing += 1;
      return acc;
    }, { web: 0, nonWeb: 0, missing: 0 });

    summary.innerHTML = [
      '<strong>Business Launcher</strong>',
      '<span class="launcher-count launcher-count-web">바로 열기 ' + counts.web + '</span>',
      '<span class="launcher-count">비웹 ' + counts.nonWeb + '</span>',
      '<span class="launcher-count">미배포 ' + counts.missing + '</span>',
      '<span class="launcher-hint">행 클릭 = 사이트 열기 · 상세 = 상태 확인</span>'
    ].join("");
    return summary;
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
    if (!row || row.querySelector(".biz-launch-actions")) return;
    var business = businessForRow(row);
    if (!business) return;

    var web = isWebSurface(business);
    var nonWeb = isNonWebSurface(business);

    row.classList.toggle("has-direct-service", web);
    row.dataset.launchMode = web ? "web" : nonWeb ? "non-web" : "detail";
    row.setAttribute(
      "aria-label",
      "B" + pad(business.number) + " " + business.title + (web ? " 사이트 열기" : " 상세 보기")
    );

    var actions = document.createElement("div");
    actions.className = "biz-launch-actions";

    if (web) {
      var open = document.createElement("a");
      open.className = "biz-launch-open";
      open.href = business.surfaceUrl;
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      open.textContent = "사이트 열기 ↗";
      open.setAttribute("aria-label", "B" + pad(business.number) + " " + business.title + " 사이트 열기");
      open.addEventListener("click", function (event) {
        event.stopPropagation();
      });
      actions.appendChild(open);
    } else {
      var state = document.createElement("span");
      state.className = "biz-launch-state";
      state.textContent = nonWeb ? "CLI/TUI" : "미배포";
      actions.appendChild(state);
    }

    var detail = document.createElement("button");
    detail.type = "button";
    detail.className = "biz-launch-detail";
    detail.textContent = "상세";
    detail.setAttribute("aria-label", "B" + pad(business.number) + " " + business.title + " 상세 보기");
    detail.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      dispatchDetail(row);
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
    window.setTimeout(switchToLauncherView, 0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
