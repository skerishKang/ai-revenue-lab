(function () {
  "use strict";

  var businesses = Array.isArray(window.PADIEM_LAB_BUSINESSES)
    ? window.PADIEM_LAB_BUSINESSES.slice()
    : [];
  var list = document.getElementById("business-list");
  var footerCount = document.getElementById("footer-count");
  var filters = Array.from(document.querySelectorAll("[data-filter]"));

  var labels = {
    LIVE: "사용 가능",
    PREVIEW: "미리보기",
    BUILDING: "만드는 중"
  };

  function safeUrl(value) {
    if (!value) return null;
    try {
      var parsed = new URL(value);
      return parsed.protocol === "https:" ? parsed.href : null;
    } catch (_) {
      return null;
    }
  }

  function safeLocalPath(value) {
    return /^\/b\d{2}\/$/.test(value || "") ? value : null;
  }

  function publicLink(item) {
    if (item.routeKind === "LOCAL_STATIC") {
      var local = safeLocalPath(item.targetPath);
      return local ? { href: local, external: false } : null;
    }
    var external = safeUrl(item.currentPublicUrl);
    return external ? { href: external, external: true } : null;
  }

  function card(item) {
    var article = document.createElement("article");
    article.className = "business-card";
    article.dataset.status = item.publicStatus;

    var number = document.createElement("div");
    number.className = "business-no";
    number.textContent = "B" + String(item.number).padStart(2, "0");

    var titleWrap = document.createElement("div");
    titleWrap.className = "business-title-wrap";
    var title = document.createElement("h3");
    title.className = "business-title";
    title.textContent = item.koreanTitle;
    var english = document.createElement("p");
    english.className = "business-en";
    english.textContent = item.title;
    titleWrap.append(title, english);

    var copy = document.createElement("div");
    copy.className = "business-copy";
    var summary = document.createElement("p");
    summary.textContent = item.summary;
    var meta = document.createElement("div");
    meta.className = "business-meta";
    var route = document.createElement("span");
    route.textContent = item.targetPath;
    var routeKind = document.createElement("span");
    routeKind.textContent = item.routeKind === "LOCAL_STATIC" ? "LAB ROUTE" : "INDEPENDENT RUNTIME";
    meta.append(route, routeKind);
    copy.append(summary, meta);

    var action = document.createElement("div");
    action.className = "business-action";
    var status = document.createElement("span");
    status.className = "status";
    status.textContent = labels[item.publicStatus] || item.publicStatus;
    action.appendChild(status);

    var destination = publicLink(item);
    if (destination) {
      var link = document.createElement("a");
      link.className = "open-link";
      link.href = destination.href;
      if (destination.external) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.innerHTML = "<span>열기</span><span aria-hidden=\"true\">↗</span>";
        link.setAttribute("aria-label", item.koreanTitle + " 새 창에서 열기");
      } else {
        link.innerHTML = "<span>열기</span><span aria-hidden=\"true\">→</span>";
        link.setAttribute("aria-label", item.koreanTitle + " 열기");
      }
      action.appendChild(link);
    } else {
      var pending = document.createElement("span");
      pending.className = "coming-soon";
      pending.textContent = "공개 준비 중";
      action.appendChild(pending);
    }

    article.append(number, titleWrap, copy, action);
    return article;
  }

  function render(filter) {
    if (!list) return;
    var visible = filter === "ALL"
      ? businesses
      : businesses.filter(function (item) { return item.publicStatus === filter; });

    list.replaceChildren.apply(list, visible.map(card));
    if (!visible.length) {
      var empty = document.createElement("p");
      empty.className = "noscript";
      empty.textContent = "현재 이 분류에서 공개할 작업이 없습니다.";
      list.appendChild(empty);
    }
  }

  filters.forEach(function (button) {
    button.addEventListener("click", function () {
      filters.forEach(function (candidate) {
        var active = candidate === button;
        candidate.classList.toggle("is-active", active);
        candidate.setAttribute("aria-pressed", active ? "true" : "false");
      });
      render(button.dataset.filter || "ALL");
    });
  });

  if (footerCount) {
    footerCount.textContent = businesses.length + " selected public works";
  }

  render("ALL");
})();
