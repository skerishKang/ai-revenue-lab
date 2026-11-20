/* #8035 ④ — administrator news management. Activate only after the admin gate. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const URL = "/api/admin/news";
  const SOURCES = { none: "없음", ai_tester: "AI 테스터", user: "사용자 의견" };
  const KINDS = { improved: "좋아진 점", fixed: "고친 점" };
  const state = { wired: false, loaded: false, busy: false, editing: null };
  const allowed = () => !$("adminContent").hidden;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function status(message) {
    const element = $("opsNewsStatus");
    element.hidden = !message;
    element.textContent = message;
  }

  function busy(on) {
    state.busy = on;
    for (const element of $("opsNewsForm").elements) element.disabled = on;
  }

  async function request(path, method = "GET", data) {
    const options = { method, credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json" } };
    if (data !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(data);
    }
    const response = await fetch(path, options);
    return response.json();
  }

  function reset() {
    state.editing = null;
    $("opsNewsForm").reset();
    $("opsNewsLinked").hidden = true;
    $("opsNewsSubmit").textContent = "새 소식 작성";
    $("opsNewsCancel").hidden = true;
  }

  function edit(row) {
    state.editing = row.number;
    for (const [field, value] of Object.entries({
      Version: row.version, Kind: row.kind, Source: row.source,
      Title: row.title, Detail: row.detail, Feedback: "",
    })) $("opsNews" + field).value = value || "";
    const linked = $("opsNewsLinked");
    linked.textContent = "현재 연결: " + ((row.feedback_ids || []).join(", ") || "없음");
    linked.hidden = false;
    $("opsNewsSubmit").textContent = "고치기 저장";
    $("opsNewsCancel").hidden = false;
  }

  function rowView(row) {
    const li = node("li", null, "ops-row ops-news-row");
    li.append(node("div", String(row.number) + "번 · " + (row.version || "버전 없음") +
      " · " + KINDS[row.kind] + " · " + SOURCES[row.source], "ops-news-meta"));
    li.append(node("strong", row.title, "ops-news-title"));
    li.append(node("p", row.detail, "ops-news-detail"));
    li.append(node("div", "의견 연결: " + ((row.feedback_ids || []).join(", ") || "없음"),
      "ops-news-meta"));
    const button = node("button", "고치기", "ops-reload");
    button.type = "button";
    button.addEventListener("click", () => { if (allowed() && !state.busy) edit(row); });
    li.append(button);
    return li;
  }

  async function load() {
    if (!allowed() || state.busy) return;
    busy(true);
    try {
      const result = await request(URL);
      if (!allowed()) return;
      if (!result.ok) {
        status("새 소식을 열 수 없습니다 (" + (result.error?.code || "오류") + ").");
        return;
      }
      const list = $("opsNewsList");
      list.replaceChildren(...result.news.map(rowView));
      if (!result.news.length) list.append(node("li", "아직 새 소식이 없습니다.", "ops-news-meta"));
      state.loaded = true;
    } catch (_) {
      status("새 소식을 불러오지 못했습니다.");
    } finally {
      busy(false);
    }
  }

  async function save(event) {
    event.preventDefault();
    if (!allowed() || state.busy) return;
    const data = {
      version: $("opsNewsVersion").value.trim(),
      kind: $("opsNewsKind").value,
      source: $("opsNewsSource").value,
      title: $("opsNewsTitle").value.trim(),
      detail: $("opsNewsDetail").value.trim(),
      feedback: $("opsNewsFeedback").value.split(/[,\s]+/).filter(Boolean),
    };
    if (!state.editing && !data.version) {
      status("배포 버전을 입력해 주세요.");
      return;
    }
    busy(true);
    let refresh = false;
    try {
      const result = await request(state.editing ? URL + "/" + state.editing : URL,
        state.editing ? "PATCH" : "POST", data);
      if (!allowed()) return;
      if (result.ok) {
        reset();
        status("저장했습니다.");
        refresh = true;
      } else {
        if (result.news) {
          edit(result.news);
          $("opsNewsFeedback").value = data.feedback.join(", ");
          refresh = true;
        }
        status((result.news ? "글은 저장됐습니다. 의견 연결을 확인해 주세요 (" : "저장할 수 없습니다 (") +
          (result.error?.code || "오류") + ").");
      }
    } catch (_) {
      status("저장 결과를 확인할 수 없습니다. 새로고침 후 확인해 주세요.");
    } finally {
      busy(false);
    }
    if (refresh) {
      await load();
      $("opsAuditReload").click();
    }
  }

  function activate() {
    if (!allowed()) return;
    if (!state.wired) {
      state.wired = true;
      $("opsNewsForm").addEventListener("submit", save);
      $("opsNewsCancel").addEventListener("click", reset);
      $("opsNewsReload").addEventListener("click", () => { status(""); void load(); });
    }
    if (!state.loaded) void load();
  }

  window.PadiemOpsNews = Object.freeze({ activate });
})();
