(() => {
  "use strict";

  const businesses = Array.isArray(window.ARL_BUSINESSES) ? window.ARL_BUSINESSES : [];
  const $ = (selector) => document.querySelector(selector);
  const tableBody = $("#business-table-body");
  const searchInput = $("#search-input");
  const stateFilter = $("#state-filter");
  const sortControl = $("#sort-control");
  let selectedNumber = null;

  const stateLabels = {
    running: "RUNNING",
    review: "REVIEW",
    planning: "PLANNING",
    reserved: "RESERVED"
  };

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  function updateMetrics() {
    const tracked = businesses.filter((item) => item.state !== "reserved").length;
    const demos = businesses.filter((item) => Boolean(item.surfaceUrl)).length;
    const needsAction = businesses.filter((item) => ["review", "planning"].includes(item.state)).length;
    const openSlots = businesses.filter((item) => item.state === "reserved").length;
    $("#metric-tracked").textContent = pad(tracked);
    $("#metric-demo").textContent = pad(demos);
    $("#metric-action").textContent = pad(needsAction);
    $("#metric-open").textContent = pad(openSlots);
    const maxNumber = Math.max(...businesses.map((item) => item.number), 0);
    $("#sidebar-range").textContent = `01–${pad(maxNumber)}`;
  }

  function filteredBusinesses() {
    const query = searchInput.value.trim().toLowerCase();
    const state = stateFilter.value;
    const sort = sortControl.value;
    const filtered = businesses.filter((item) => {
      const haystack = `${item.number} ${pad(item.number)} ${item.title} ${item.koreanTitle} ${item.slug}`.toLowerCase();
      return (!query || haystack.includes(query)) && (state === "all" || item.state === state);
    });

    return filtered.sort((a, b) => {
      if (sort === "number-desc") return b.number - a.number;
      if (sort === "priority") return b.priority - a.priority || a.number - b.number;
      if (sort === "progress") return b.progress - a.progress || a.number - b.number;
      return a.number - b.number;
    });
  }

  function rowTemplate(item) {
    const selectedClass = item.number === selectedNumber ? " is-selected" : "";
    const reservedClass = item.state === "reserved" ? " is-reserved" : "";
    return `
      <tr class="business-row${selectedClass}${reservedClass}" data-business-number="${item.number}" tabindex="0" aria-selected="${item.number === selectedNumber}">
        <td>
          <div class="business-id">
            <span class="business-number">${pad(item.number)}</span>
            <span class="business-title">
              <strong>${item.title}</strong>
              <span>${item.koreanTitle}</span>
            </span>
          </div>
        </td>
        <td><span class="status-badge status-${item.state}">${stateLabels[item.state]}</span></td>
        <td class="progress-cell">
          <div class="progress-label"><span>DEMO</span><span>${item.progress}%</span></div>
          <div class="progress-track"><i style="width:${item.progress}%"></i></div>
        </td>
        <td class="mono-cell">${item.surfaceType}</td>
        <td class="mono-cell">${item.githubLabel}</td>
        <td class="action-cell">${item.nextAction}</td>
      </tr>
    `;
  }

  function renderTable() {
    const visible = filteredBusinesses();
    tableBody.innerHTML = visible.map(rowTemplate).join("") || '<tr><td colspan="6" class="empty-state">검색 조건에 맞는 사업이 없습니다.</td></tr>';
    $("#result-count").textContent = `${visible.length} rows`;

    tableBody.querySelectorAll(".business-row").forEach((row) => {
      const select = () => selectBusiness(Number(row.dataset.businessNumber));
      row.addEventListener("click", select);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
    });
  }

  function configureLink(selector, url) {
    const link = $(selector);
    if (url) {
      link.href = url;
      link.rel = "noopener noreferrer";
      link.classList.remove("is-disabled");
      link.removeAttribute("aria-disabled");
    } else {
      link.href = "#";
      link.classList.add("is-disabled");
      link.setAttribute("aria-disabled", "true");
    }
  }

  function selectBusiness(number) {
    const item = businesses.find((business) => business.number === number);
    if (!item) return;
    selectedNumber = number;
    $("#detail-number").textContent = `BUSINESS ${pad(item.number)}`;
    $("#detail-status").className = `status-badge status-${item.state}`;
    $("#detail-status").textContent = stateLabels[item.state];
    $("#detail-title").textContent = item.title;
    $("#detail-korean").textContent = item.koreanTitle;
    $("#detail-progress-value").textContent = `${item.progress}%`;
    $("#detail-progress-bar").style.width = `${item.progress}%`;
    $("#detail-lifecycle").textContent = item.lifecycle;
    $("#detail-workspace").textContent = item.workspace;
    $("#detail-deployment").textContent = item.deployment;
    $("#detail-github").textContent = item.githubLabel;
    $("#detail-verified").textContent = item.lastVerified;
    $("#detail-next-action").textContent = item.nextAction;
    configureLink("#surface-link", item.surfaceUrl);
    configureLink("#github-link", item.githubUrl);
    configureLink("#issue-link", item.issueUrl);
    $("#action-note").textContent = item.surfaceUrl
      ? "확인된 배포 주소와 GitHub 근거만 연결되어 있습니다."
      : "확인된 배포 주소가 없어 GitHub 근거만 활성화했습니다.";
    renderTable();
  }

  function renderPriorityActions() {
    const actions = businesses
      .filter((item) => item.priority > 0 && item.state !== "reserved")
      .sort((a, b) => b.priority - a.priority)
      .slice(0, 6);

    $("#priority-count").textContent = `${actions.length} items`;
    $("#priority-list").innerHTML = actions.map((item) => `
      <button class="priority-item" type="button" data-priority-number="${item.number}">
        <span class="priority-number">BIZ ${pad(item.number)}</span>
        <span class="priority-title">${item.title}</span>
        <span class="priority-action">${item.nextAction}</span>
        <span class="priority-score">P${item.priority}</span>
      </button>
    `).join("");

    document.querySelectorAll("[data-priority-number]").forEach((button) => {
      button.addEventListener("click", () => selectBusiness(Number(button.dataset.priorityNumber)));
    });
  }

  [searchInput, stateFilter, sortControl].forEach((control) => {
    control.addEventListener(control === searchInput ? "input" : "change", renderTable);
  });

  $("#refresh-button").addEventListener("click", () => window.location.reload());
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((nav) => nav.classList.remove("is-active"));
      item.classList.add("is-active");
      if (item.dataset.view !== "businesses") {
        $("#action-note").textContent = `${item.textContent.trim()} 화면은 다음 단계에서 연결할 수 있습니다.`;
      }
    });
  });

  updateMetrics();
  renderTable();
  renderPriorityActions();
  const firstAction = businesses.find((item) => item.priority === Math.max(...businesses.map((entry) => entry.priority)));
  if (firstAction) selectBusiness(firstAction.number);
})();
