/* legal-demo.js — the B67 static review surface controller.
 *
 * Wires the shared Claw shell (js/claw-shell.js, js/claw-evidence.js) to the
 * Legal vertical (legal/legal-authority.js, legal/legal-evidence-provenance.js)
 * and exposes the nine reviewable states from #3138 as a switcher:
 *
 *   A. 새 조사 (home)          F. 근거 없음 (fail-closed)
 *   B. 통합 검색 결과            G. Drive 미연결
 *   C. 공식 법률자료 중심        H. Desktop evidence panel (width-driven)
 *   D. 내 Drive 문서 검색        I. Mobile evidence drawer (width-driven)
 *   E. PDF page provenance
 *
 * H and I are not separate states: they are the same evidence list served two
 * ways by the same code, which is exactly the property that has to hold before
 * this surface is absorbed into Claw.
 *
 * Everything rendered here is MOCK data from data/demo-corpus.js.
 */
(function (global) {
  "use strict";

  var el = global.ClawShell.el;
  var clear = global.ClawShell.clear;
  var Legal = global.B67Legal;
  var Demo = global.B67Demo;

  var STORAGE_KEY = "b67-legal-demo-state";

  var STATES = [
    { id: "home", label: "A · 새 조사" },
    { id: "unified", label: "B · 통합 검색" },
    { id: "official", label: "C · 공식 법률자료" },
    { id: "drive", label: "D · 내 Drive" },
    { id: "provenance", label: "E · 페이지 provenance" },
    { id: "fail-closed", label: "F · 근거 없음" },
    { id: "disconnected", label: "G · Drive 미연결" }
  ];

  var store = global.ClawShell.createStore({
    view: "conversation",
    state: "unified",
    scope: "unified",
    matter: Demo.MATTERS[0].id,
    activeN: 2,
    evidence: [],
    answer: null,
    driveConnected: true,
    drawerOpen: false
  });

  var dom = {};
  var renderer = null;
  var traps = { drawer: null, sidebar: null };

  /* ── Evidence selection per state ──────────────────────────────────────── */
  function evidenceForState(stateId) {
    switch (stateId) {
      case "official":
        return Demo.EVIDENCE.filter(function (r) { return r.source_type === "official"; });
      case "drive":
        return Demo.EVIDENCE.filter(function (r) { return r.source_type === "drive"; });
      case "provenance":
        return Demo.EVIDENCE.filter(function (r) { return r.page_or_section; });
      case "fail-closed":
      case "disconnected":
        return [];
      case "home":
        return [];
      case "unified":
      default:
        return Demo.EVIDENCE.slice();
    }
  }

  function isFailClosedState(stateId) {
    return stateId === "fail-closed" || stateId === "disconnected";
  }

  /* ── Sidebar: matters + corpus + format strip ─────────────────────────── */
  function renderSidebar() {
    var state = store.get();

    /* Recent matters */
    clear(dom.matterList);
    Demo.MATTERS.forEach(function (matter) {
      dom.matterList.appendChild(el("button", {
        type: "button",
        class: "recent-item",
        "data-matter": matter.id,
        "aria-current": matter.id === state.matter ? "true" : "false",
        onClick: function () { store.set({ matter: matter.id }); }
      }, [
        el("span", { text: matter.title }),
        el("span", {
          style: "margin-left:auto;color:rgba(255,255,255,.38);font-size:11px;white-space:nowrap;",
          text: matter.period
        })
      ]));
    });

    /* Drive corpus — DEMO state is stated in the block itself, not only in a
     * global banner, so a screenshot of the sidebar alone is still honest. */
    clear(dom.corpus);
    var corpusState = state.driveConnected ? "demo" : "disconnected";
    var corpusLabel = state.driveConnected ? "연결됨 — DEMO" : "연결 안 됨";

    var head = el("div", { class: "corpus-head" }, [
      el("span", { "aria-hidden": "true", text: "▤" }),
      el("span", { text: "Google Drive" })
    ]);
    head.appendChild(el("span", {
      class: "corpus-state",
      "data-state": corpusState,
      text: corpusLabel
    }));
    dom.corpus.appendChild(head);

    if (!state.driveConnected) {
      dom.corpus.appendChild(el("p", {
        class: "corpus-empty",
        text: "Drive가 연결되어 있지 않습니다. 사건 자료를 불러오려면 먼저 연결해야 합니다."
      }));
      dom.corpus.appendChild(el("button", {
        type: "button",
        class: "recent-item",
        style: "justify-content:center;",
        text: "Google Drive 연결",
        onClick: function () { store.set({ driveConnected: true }); }
      }));
    } else {
      Demo.CORPUS.forEach(function (doc) {
        dom.corpus.appendChild(el("button", {
          type: "button",
          class: "corpus-doc",
          "data-doc-id": doc.id,
          onClick: function () {
            if (doc.support === "unsupported") {
              dom.runtimeNote.textContent =
                "레거시 .hwp는 현재 표준 문서 경로에서 지원하지 않습니다. 이 파일은 열 수 없습니다.";
              return;
            }
            dom.runtimeNote.textContent =
              "샘플 문서 '" + doc.name + "' — 실제 문서 열기는 아직 연결되지 않았습니다.";
          }
        }, [
          el("span", { class: "corpus-doc-kind", text: doc.kind }),
          el("span", { class: "corpus-doc-name", text: doc.name }),
          doc.pages ? el("span", { class: "corpus-doc-pages", text: doc.pages + "p" }) : null
        ]));
      });
      dom.corpus.appendChild(el("p", {
        class: "corpus-empty",
        text: "샘플 자료실 · 실제 Drive 폴더 연결 없음"
      }));
    }

    /* Honest format matrix, always visible. */
    clear(dom.formatStrip);
    Demo.FORMAT_SUPPORT.forEach(function (row) {
      dom.formatStrip.appendChild(el("li", { class: "fmt-row", "data-support": row.support }, [
        el("span", { class: "fmt-key", text: row.key }),
        el("span", { class: "fmt-state", text: row.state })
      ]));
    });
  }

  /* ── Conversation column ──────────────────────────────────────────────── */
  function renderConversation() {
    var state = store.get();
    clear(dom.conversation);

    if (state.state === "home") {
      dom.conversation.appendChild(renderEmptyState());
      return;
    }

    /* Scope bar */
    var scope = Legal.scopeById(state.state === "fail-closed" || state.state === "disconnected" ? "unified" : state.state);
    var bar = el("div", { class: "scope-bar" }, [
      el("p", { class: "scope-bar-label", text: "검색 범위" })
    ]);
    var chips = el("div", { class: "claw-chips", role: "group", "aria-label": "검색 범위 선택" });
    Legal.SCOPES.forEach(function (s) {
      chips.appendChild(el("button", {
        type: "button",
        class: "claw-chip",
        "data-value": s.id,
        "aria-pressed": s.id === scope.id ? "true" : "false",
        onClick: function () {
          store.set({ scope: s.id, state: s.id === "official" || s.id === "drive" ? s.id : "unified" });
        }
      }, [
        el("span", { class: "chip-icon", "aria-hidden": "true", text: s.icon }),
        el("span", { text: s.label })
      ]));
    });
    bar.appendChild(chips);
    bar.appendChild(el("p", { class: "scope-note", text: scope.note }));
    dom.conversation.appendChild(bar);

    if (isFailClosedState(state.state)) {
      dom.conversation.appendChild(renderFailClosed(state));
      return;
    }

    /* The user turn */
    var answer = Demo.SAMPLE_ANSWER;
    dom.conversation.appendChild(el("article", { class: "message user-message" }, [
      el("div", { class: "message-bubble", text: answer.prompt })
    ]));

    /* Run status — transcribed from the canonical .claw-status idiom. */
    dom.conversation.appendChild(el("p", {
      class: "run-status",
      "data-state": answer.run.status
    }, [
      el("span", { class: "run-dot", "aria-hidden": "true" }),
      el("span", { text: "깊이 검색 " + answer.run.searches + "회 · 근거 " + answer.run.sources + "개 · 샘플 결과" })
    ]));

    /* The assistant turn */
    var body = el("div", { class: "assistant-body" });
    body.appendChild(el("div", { class: "assistant-meta" }, [
      el("span", { text: "Padiem Legal" }),
      el("span", { class: "demo-label", text: "DEMO · 샘플 근거" })
    ]));

    var content = el("div", { class: "assistant-content" });
    answer.paragraphs.forEach(function (para) {
      var p = el("p");
      para.segments.forEach(function (seg) {
        if (seg.cite) {
          p.appendChild(el("button", {
            type: "button",
            class: "cite",
            "data-cite": seg.cite,
            "aria-current": seg.cite === state.activeN ? "true" : "false",
            "aria-label": seg.cite + "번 근거로 이동",
            text: "[" + seg.cite + "]",
            onClick: function () { applyState({ activeN: seg.cite, drawerOpen: true }); }
          }));
        } else {
          p.appendChild(document.createTextNode(seg.t));
        }
      });
      content.appendChild(p);
    });
    body.appendChild(content);

    /* A grounded answer must carry its own scope + a way to see the evidence. */
    body.appendChild(el("div", { class: "answer-actions" }, [
      el("button", {
        type: "button",
        class: "answer-action",
        onClick: function () { store.set({ drawerOpen: true }); }
      }, [
        el("span", { class: "action-icon", "aria-hidden": "true", text: "⌗" }),
        el("span", { text: "근거 " + state.evidence.length + "개 보기" })
      ]),
      el("button", {
        type: "button",
        class: "answer-action",
        text: "검색 범위 바꾸기",
        onClick: function () { applyState({ state: "unified", scope: "unified" }); }
      })
    ]));
    body.appendChild(el("p", {
      class: "composer-note",
      style: "text-align:left;margin:4px 0 0;",
      text: "이 답변은 샘플 데이터로 구성한 시연이며 실제 사건 분석이 아닙니다. 인용된 근거는 모두 가상 자료입니다."
    }));

    dom.conversation.appendChild(el("article", { class: "message assistant-message" }, [
      el("div", { class: "assistant-avatar", "aria-hidden": "true", text: "P" }),
      body
    ]));
  }

  function renderEmptyState() {
    var wrap = el("div", { class: "empty-state" });
    wrap.appendChild(el("p", { class: "eyebrow", text: "PADIEM LEGAL · B67" }));
    wrap.appendChild(el("h1", null, [
      document.createTextNode("근거부터 찾는 "),
      el("em", { text: "법률 조사" }),
      document.createTextNode(" 워크스페이스")
    ]));
    wrap.appendChild(el("p", {
      class: "empty-copy",
      text: "질문하면 공식 법률자료와 내 자료에서 근거를 찾아出处를 붙입니다. 확인되지 않은 내용은 결론으로 제시하지 않습니다."
    }));

    var starters = [
      { icon: "⚖", title: "계약 해지 시점 확인", copy: "상대방이 해지를 처음 주장한 시점과 근거 자료", prompt: Demo.SAMPLE_ANSWER.prompt },
      { icon: "▤", title: "내 자료에서 검색", copy: "사건 자료실에서 문서 찾기", prompt: "이 사건 자료실에서 상대방이 보낸 메일을 찾아줘." },
      { icon: "◇", title: "요건 정리", copy: "주장 요건에 해당하는 조문 찾기", prompt: "계약 해지 주장이 성립하려면 어떤 요건이 필요한지 찾아줘." }
    ];
    var grid = el("div", { class: "starter-grid" });
    starters.forEach(function (s) {
      grid.appendChild(el("button", {
        type: "button",
        class: "starter",
        onClick: function () {
          dom.composerInput.value = s.prompt;
          store.set({ state: "unified", scope: "unified" });
          dom.composerInput.focus();
        }
      }, [
        el("span", { class: "starter-icon", "aria-hidden": "true", text: s.icon }),
        el("span", null, [
          el("strong", { text: s.title }),
          el("small", { text: s.copy })
        ])
      ]));
    });
    wrap.appendChild(grid);
    wrap.appendChild(el("p", {
      class: "composer-note",
      style: "text-align:left;margin-top:22px;",
      text: "이 화면은 정적 시연입니다. 검색·문서 열기·Drive 연결은 실제 동작하지 않습니다."
    }));
    return wrap;
  }

  function renderFailClosed(state) {
    var fc = Demo.FAIL_CLOSED;
    var wrap = el("div", { class: "empty-state" });

    var card = el("div", { class: "ev-empty", style: "max-width:560px;" });
    card.appendChild(el("p", { class: "ev-empty-title", style: "font-size:16px;", text: fc.title }));
    card.appendChild(el("p", { class: "ev-empty-body", text: fc.body }));
    card.appendChild(el("p", { class: "ev-empty-body", text: fc.reason }));

    var actions = el("div", { class: "ev-actions" });
    fc.actions.forEach(function (action) {
      actions.appendChild(el("button", {
        type: "button",
        class: "ev-action" + (action.id === "widen" ? " is-primary" : ""),
        text: action.label,
        onClick: function () {
          if (action.id === "widen") {
            applyState({ state: "unified", scope: "unified" });
          } else {
            applyState({ state: "drive", scope: "drive" });
          }
        }
      }));
    });
    card.appendChild(actions);
    wrap.appendChild(card);

    /* The no-answer turn is still rendered, so the conversation history is
     * honest: the system responded, it just did not assert anything. */
    var body = el("div", { class: "assistant-body" });
    body.appendChild(el("div", { class: "assistant-meta" }, [
      el("span", { text: "Padiem Legal" }),
      el("span", { class: "demo-label", text: "DEMO · 근거 없음" })
    ]));
    body.appendChild(el("div", { class: "assistant-content" }, [
      el("p", { text: fc.body })
    ]));
    wrap.appendChild(el("article", { class: "message assistant-message", style: "margin-top:22px;" }, [
      el("div", { class: "assistant-avatar", "aria-hidden": "true", text: "P" }),
      body
    ]));

    wrap.appendChild(el("p", {
      class: "composer-note",
      style: "text-align:left;margin-top:18px;",
      text: "근거가 없는 상태에서 법률 결론을 생성하지 않는 것은 이 제품의 기본 동작입니다."
    }));

    return wrap;
  }

  /* ── Evidence surfaces ────────────────────────────────────────────────── */
  function renderEvidence() {
    var state = store.get();
    var records = state.evidence;
    var emptyState = isFailClosedState(state.state)
      ? { title: "표시할 근거가 없습니다.", body: "답변에 인용할 수 있는 근거가 확인되지 않았습니다.", reason: null }
      : null;

    var ctx = { activeN: state.activeN };
    renderer.render(dom.evidenceList, records, ctx, emptyState);
    renderer.render(dom.drawerList, records, ctx, emptyState);

    dom.evidenceCount.textContent = records.length + "개";
    dom.drawerCount.textContent = records.length + "개";
    var trigger = dom.evidenceTrigger;
    trigger.querySelector(".trigger-label").textContent = "근거 " + records.length + "개";
    trigger.disabled = records.length === 0;
    trigger.setAttribute("aria-disabled", records.length === 0 ? "true" : "false");
  }

  function syncDrawer() {
    var open = store.get().drawerOpen;
    dom.drawer.setAttribute("data-open", open ? "true" : "false");
    dom.drawerScrim.hidden = !open;
    /* Keep the sheet in the DOM so it can animate; inert it when closed so it
     * never traps focus or gets read by a screen reader. */
    dom.drawer.inert = !open;
    dom.evidenceTrigger.setAttribute("aria-expanded", open ? "true" : "false");
    /* The focus half is defensive on purpose: rendering must never be able to
     * throw, because a throw here would abort the caller's control flow. */
    if (!traps.drawer) return;
    if (open) traps.drawer.open();
    else if (traps.drawer.isActive()) traps.drawer.close();
  }

  function openLocator(record) {
    dom.runtimeNote.textContent =
      "샘퍼 위치 '" + (record.page_or_section || "") + "' — 실제 문서 뷰어는 아직 연결되지 않았습니다.";
    applyState({ activeN: record.n, drawerOpen: true });
  }

  /* ── State switching ──────────────────────────────────────────────────── */
  /* The store is the single source of truth. Every mutation goes through
   * store.set(), and a single subscription drives all rendering — so a handler
   * that only sets state can never leave the UI out of sync with it. */
  function applyState(patch) {
    var next = Object.assign({}, patch);
    if (next.state !== undefined) {
      next.evidence = evidenceForState(next.state);
      if (next.state === "disconnected") next.driveConnected = false;
      if (next.state === "home") next.drawerOpen = false;
      if (next.state === "provenance") {
        next.evidence = evidenceForState("provenance");
        next.activeN = 1;
      }
    }
    store.set(next);
    persist();
  }

  function persist() {
    try { localStorage.setItem(STORAGE_KEY, store.get().state); } catch (e) { /* private mode */ }
  }

  function restore() {
    var saved;
    try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) { saved = null; }
    if (saved && STATES.some(function (s) { return s.id === saved; })) applyState({ state: saved });
  }

  function renderAll() {
    var state = store.get();
    dom.shell.setAttribute("data-view", state.state === "home" ? "home" : "conversation");
    dom.topbarTitle.textContent = state.state === "home"
      ? "새 조사"
      : (Legal.scopeById(state.scope).label + " · " + (Demo.MATTERS[0].title));
    dom.evidencePanel.hidden = state.state === "home";
    dom.evidenceTriggerRow.hidden = state.state === "home";

    Array.prototype.forEach.call(dom.stateChips.querySelectorAll("[data-value]"), function (chip) {
      chip.setAttribute("aria-pressed", chip.getAttribute("data-value") === state.state ? "true" : "false");
    });

    renderSidebar();
    renderConversation();
    renderEvidence();
    syncDrawer();
  }

  /* ── Sidebar drawer (mobile) ──────────────────────────────────────────── */
  var syncing = false;

  function syncSidebar() {
    if (syncing) return;
    syncing = true;
    try {
      var mobile = window.matchMedia("(max-width: 920px)").matches;
      var open = mobile && dom.shell.classList.contains("sidebar-open");
      // Idempotent write: only touch the class when it actually differs.
      // DOMTokenList.remove() calls setAttribute, which fires an attribute
      // mutation record even when the value is unchanged, so an unconditional
      // remove() inside a class observer deadlocks the renderer.
      if (!mobile && dom.shell.classList.contains("sidebar-open")) {
        dom.shell.classList.remove("sidebar-open");
      }
      dom.sidebar.inert = !open;
      dom.mainPanel.inert = open;
      dom.menuButton.setAttribute("aria-expanded", open ? "true" : "false");
      dom.sidebarScrim.hidden = !open;
    } finally {
      syncing = false;
    }
  }

  /* ── Boot ─────────────────────────────────────────────────────────────── */
  function init() {
    dom = {
      shell: document.getElementById("appShell"),
      sidebar: document.getElementById("sidebar"),
      mainPanel: document.getElementById("mainPanel"),
      sidebarScrim: document.getElementById("sidebarScrim"),
      menuButton: document.getElementById("mobileMenu"),
      sidebarClose: document.getElementById("sidebarClose"),
      topbarTitle: document.getElementById("topbarTitle"),
      matterList: document.getElementById("matterList"),
      corpus: document.getElementById("corpus"),
      formatStrip: document.getElementById("formatStrip"),
      stateChips: document.getElementById("stateChips"),
      conversation: document.getElementById("conversation"),
      evidencePanel: document.getElementById("evidencePanel"),
      evidenceList: document.getElementById("evidenceList"),
      evidenceCount: document.getElementById("evidenceCount"),
      evidenceTriggerRow: document.getElementById("evidenceTriggerRow"),
      evidenceTrigger: document.getElementById("evidenceTrigger"),
      drawer: document.getElementById("evidenceDrawer"),
      drawerList: document.getElementById("drawerList"),
      drawerScrim: document.getElementById("drawerScrim"),
      drawerClose: document.getElementById("drawerClose"),
      panelClose: document.getElementById("panelClose"),
      drawerCount: document.getElementById("drawerCount"),
      composerInput: document.getElementById("composerInput"),
      sendButton: document.getElementById("sendButton"),
      runtimeNote: document.getElementById("runtimeNote"),
      newResearch: document.getElementById("newResearch")
    };

    renderer = global.ClawEvidence.createRenderer({
      decorator: global.B67LegalEvidence.createDecorator({ onLocator: openLocator }),
      sourceTypeLabel: Legal.sourceTypeLabel,
      onOpen: function (record) {
        dom.runtimeNote.textContent =
          "샘플 원문 '" + (record.title || "") + "' — 실제 원문 열기는 아직 연결되지 않았습니다.";
      },
      onLocator: openLocator,
      onEmptyAction: function (actionId) {
        if (actionId === "widen") applyState({ state: "unified", scope: "unified" });
        if (actionId === "check-drive") applyState({ state: "drive", scope: "drive" });
      }
    });

    /* Initial evidence, set before the subscription is installed so the
     * explicit renderAll() at the end of init() owns the first paint. */
    store.set({ evidence: evidenceForState("unified") });

    /* Demo state switcher */
    global.ClawShell.bindToggleGroup(dom.stateChips, function (value) { applyState({ state: value }); });

    /* Scope chips are re-rendered per conversation pass, so they are bound by
     * delegation on the conversation container instead of a static group. */
    dom.conversation.addEventListener("click", function (event) {
      var chip = event.target.closest('.claw-chip[data-value]');
      if (!chip) return;
      var value = chip.getAttribute("data-value");
      applyState({ scope: value, state: value === "official" || value === "drive" ? value : "unified" });
    });

    /* Composer */
    global.ClawShell.bindComposer(dom.composerInput, dom.sendButton, function (text) {
      dom.composerInput.value = "";
      dom.sendButton.disabled = true;
      applyState({ state: "unified", scope: "unified" });
      dom.runtimeNote.textContent = "샘플 답변을 표시했습니다. 실제 검색은 연결되지 않았습니다.";
    });

    /* Drawer + sidebar traps */
    traps.drawer = global.ClawShell.createFocusTrap(dom.drawer, function () {
      applyState({ drawerOpen: false });
    });
    traps.sidebar = global.ClawShell.createFocusTrap(dom.sidebar, function () {
      dom.shell.classList.remove("sidebar-open");
      syncSidebar();
    });

    dom.evidenceTrigger.addEventListener("click", function () { applyState({ drawerOpen: true }); });
    dom.drawerClose.addEventListener("click", function () { applyState({ drawerOpen: false }); });
    dom.drawerScrim.addEventListener("click", function () { applyState({ drawerOpen: false }); });

    dom.panelClose.addEventListener("click", function () {
      applyState({ state: "home", scope: "unified" });
    });

    dom.menuButton.addEventListener("click", function () {
      dom.shell.classList.toggle("sidebar-open");
      syncSidebar();
      if (dom.shell.classList.contains("sidebar-open")) traps.sidebar.open();
      else if (traps.sidebar.isActive()) traps.sidebar.close();
    });
    dom.sidebarClose.addEventListener("click", function () {
      dom.shell.classList.remove("sidebar-open");
      syncSidebar();
    });
    dom.sidebarScrim.addEventListener("click", function () {
      dom.shell.classList.remove("sidebar-open");
      syncSidebar();
    });

    dom.newResearch.addEventListener("click", function () {
      applyState({ state: "home", scope: "unified" });
      dom.composerInput.focus();
    });

    /* Clicking an evidence card anywhere highlights it in both surfaces. */
    [dom.evidenceList, dom.drawerList].forEach(function (list) {
      list.addEventListener("click", function (event) {
        var cardNode = event.target.closest(".ev");
        if (!cardNode) return;
        var n = parseInt(cardNode.getAttribute("data-evidence-n"), 10);
        if (!isNaN(n)) applyState({ activeN: n });
      });
    });

    /* Keep the drawer a11y state self-healing if the class is toggled
     * anywhere else — transcribed from the canonical MutationObserver. */
    if (window.MutationObserver) {
      new MutationObserver(syncSidebar)
        .observe(dom.shell, { attributes: true, attributeFilter: ["class"] });
    }
    window.matchMedia("(max-width: 920px)")
      .addEventListener("change", function () {
        syncSidebar();
        if (!traps.sidebar.isActive()) return;
        if (!dom.shell.classList.contains("sidebar-open")) traps.sidebar.close();
      });

    /* Subscribe only once every handler and trap exists, so no render can be
     * triggered from a half-built surface. */
    store.subscribe(function () { renderAll(); });

    syncSidebar();
    renderAll();
    restore();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.B67DemoApp = { store: store, STATES: STATES, applyState: applyState, evidenceForState: evidenceForState };
})(window);
