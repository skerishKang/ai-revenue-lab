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
 * THREE INVARIANTS this file exists to keep true (each one was a real bug,
 * each has a browser regression in tests/verify_browser.py):
 *
 *   1. `state` is the SINGLE source of truth. Title, scope chip, and evidence
 *      are all DERIVED from it. There is no second `scope` field that can drift.
 *
 *   2. The evidence surface follows the viewport. Desktop (>920px) uses the
 *      right-hand panel; tablet/mobile (<=920px) uses the bottom sheet. A
 *      citation click never opens the sheet on desktop.
 *
 *   3. Disconnected means disconnected. While Drive is not connected, NO Drive
 *      evidence may be produced by any state — a citation that cites a document
 *      the UI says it cannot see is the exact failure this product forbids.
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

  /* The TOP-BAR REVIEW SWITCHER — a UI affordance, NOT the set of valid
   * states. `web` is a real routable scope that deliberately has no chip here,
   * so this list must never be used to validate persisted state. */
  var REVIEW_STATES = [
    { id: "home", label: "A · 새 조사" },
    { id: "unified", label: "B · 통합 검색" },
    { id: "official", label: "C · 공식 법률자료" },
    { id: "drive", label: "D · 내 Drive" },
    { id: "provenance", label: "E · 페이지 provenance" },
    { id: "fail-closed", label: "F · 근거 없음" },
    { id: "disconnected", label: "G · Drive 미연결" }
  ];

  /* `state` is the only routing authority. Title, scope chip, and evidence are
   * derived from it via scopeForState()/titleForState()/evidenceForState().
   * A `scope` field used to live here too, and the two drifted apart. */
  var store = global.ClawShell.createStore({
    view: "conversation",
    state: "unified",
    matter: Demo.MATTERS[0].id,
    activeN: 2,
    evidence: [],
    driveConnected: true,
    driveRequired: false,
    drawerOpen: false
  });

  /* The desktop/mobile split that decides panel vs bottom sheet. Matches the
   * CSS breakpoint exactly; a second number here would desynchronise them. */
  function isSheetViewport() {
    return window.matchMedia("(max-width: 920px)").matches;
  }

  var dom = {};
  var renderer = null;
  var composer = null;
  var traps = { drawer: null, sidebar: null };

  /* ── Derived routing views ──────────────────────────────────────────────
   * These three functions are the ONLY places that turn `state` into something
   * the user sees. Keeping them pure and adjacent makes it obvious that there
   * is a single authority. */

  /* Every routable scope. `web` was missing here, which is why the visible 웹
   * chip snapped back to 통합 on click — the control looked real and was not. */
  var ROUTABLE_STATES = ["unified", "official", "drive", "web"];

  /* THE canonical valid-state authority: what may be persisted and restored.
   *
   * DERIVED, never hand-maintained. It was previously the review-switcher list,
   * which is a different concern: the switcher is what we choose to show, while
   * this is what the state machine can actually represent. Conflating them made
   * `web` persistable-but-unrestorable — a real routable scope that silently
   * reverted to 통합 on reload. Deriving it means a new routable scope is
   * restorable the moment it is routable. */
  var PERSISTABLE_STATES = ROUTABLE_STATES.concat(
    REVIEW_STATES.map(function (entry) { return entry.id; })
      .filter(function (id) { return ROUTABLE_STATES.indexOf(id) === -1; })
  );

  function isPersistable(stateId) {
    return PERSISTABLE_STATES.indexOf(stateId) !== -1;
  }

  function scopeForState(stateId) {
    if (ROUTABLE_STATES.indexOf(stateId) !== -1) return stateId;
    return "unified";
  }

  function titleForState(stateId) {
    switch (stateId) {
      case "home": return "새 조사";
      case "official": return "공식 법률자료";
      case "drive": return "내 Drive";
      case "web": return "웹";
      case "provenance": return "페이지 provenance";
      case "fail-closed": return "근거 없음";
      case "disconnected": return "Drive 미연결";
      default: return "통합";
    }
  }

  function titleFor(state) {
    var matter = matterById(state.matter);
    var base = titleForState(state.state);
    if (state.state === "home" || !matter) return base;
    return base + " · " + matter.title;
  }

  function matterById(id) {
    for (var i = 0; i < Demo.MATTERS.length; i += 1) {
      if (Demo.MATTERS[i].id === id) return Demo.MATTERS[i];
    }
    return Demo.MATTERS[0];
  }

  /* ── Evidence selection per state ────────────────────────────────────────
   * `driveConnected` is a FILTER, not a label. When Drive is disconnected the
   * Drive records are removed from every state, so no citation can ever point
   * at a document the sidebar says it cannot see. */
  function evidenceForState(stateId, driveConnected) {
    var records;
    switch (stateId) {
      case "official":
        records = Demo.EVIDENCE.filter(function (r) { return r.source_type === "official"; });
        break;
      case "web":
        records = Demo.EVIDENCE.filter(function (r) { return r.source_type === "web"; });
        break;
      case "drive":
        records = Demo.EVIDENCE.filter(function (r) { return r.source_type === "drive"; });
        break;
      case "provenance":
        records = Demo.EVIDENCE.filter(function (r) { return r.page_or_section; });
        break;
      case "fail-closed":
      case "disconnected":
      case "home":
        records = [];
        break;
      case "unified":
      default:
        records = Demo.EVIDENCE.slice();
        break;
    }
    if (driveConnected) return records;
    return records.filter(function (r) { return r.source_type !== "drive"; });
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
        onClick: function () { applyState({ matter: matter.id }); }
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
        text: "Google Drive 연결 (DEMO)",
        onClick: function () { applyState({ driveConnected: true }); }
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
      /* Say plainly that the corpus is shared demo data, so selecting another
       * matter does not silently imply it has different documents. */
      dom.corpus.appendChild(el("p", {
        class: "corpus-empty",
        text: "모든 사건에 동일한 샘플 자료를 사용합니다"
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
    var runSources = state.evidence.length;
    clear(dom.conversation);

    if (state.state === "home") {
      dom.conversation.appendChild(renderEmptyState());
      return;
    }

    /* Scope bar */
    /* The scope bar is DERIVED from state, and its clicks are handled by the
     * single delegated listener on the conversation container. There is
     * deliberately no per-button onClick: two paths meant one click could
     * render twice with a stale scope in between. */
    var scope = Legal.scopeById(scopeForState(state.state));
    var bar = el("div", { class: "scope-bar" }, [
      el("p", { class: "scope-bar-label", text: "검색 범위" })
    ]);
    var chips = el("div", { class: "claw-chips", role: "group", "aria-label": "검색 범위 선택" });
    Legal.SCOPES.forEach(function (s) {
      chips.appendChild(el("button", {
        type: "button",
        class: "claw-chip",
        "data-value": s.id,
        "aria-pressed": s.id === scope.id ? "true" : "false"
      }, [
        el("span", { class: "chip-icon", "aria-hidden": "true", text: s.icon }),
        el("span", { text: s.label })
      ]));
    });
    bar.appendChild(chips);
    bar.appendChild(el("p", { class: "scope-note", text: scope.note }));
    dom.conversation.appendChild(bar);

    if (isFailClosedState(state.state) || state.driveRequired) {
      dom.conversation.appendChild(renderFailClosed(state));
      return;
    }

    /* The user turn. Each scope has its own grounded answer, because each
     * scope can only see a different subset of the corpus. */
    var answer = Demo.ANSWERS[scopeForState(state.state)] || Demo.SAMPLE_ANSWER;

    /* CITATION INTEGRITY GATE.
     *
     * The sample answer is fixed text, but the evidence set is not. If any
     * citation in the answer has no matching record in the panel, the answer
     * is not groundable and must NOT be rendered — a claim pointing at a
     * document the interface cannot show is the exact failure this product
     * exists to prevent. Real backends guarantee this by construction; a
     * static surface has to check it. */
    if (!citationsResolve(answer, state.evidence)) {
      dom.conversation.appendChild(renderFailClosed(state));
      return;
    }
    /* The run-status line reports the scope's own numbers, not one global set. */
    runSources = answer.run.sources;

    dom.conversation.appendChild(el("article", { class: "message user-message" }, [
      el("div", { class: "message-bubble", text: answer.prompt })
    ]));

    /* Run status — transcribed from the canonical .claw-status idiom. */
    dom.conversation.appendChild(el("p", {
      class: "run-status",
      "data-state": answer.run.status
    }, [
      el("span", { class: "run-dot", "aria-hidden": "true" }),
      el("span", { text: "깊이 검색 " + answer.run.searches + "회 · 근거 " + runSources + "개 · 샘플 결과" })
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
            /* Stable id so the drawer focus trap can return focus here after
             * the conversation is re-rendered by this very click. */
            id: "cite-" + seg.cite,
            "aria-current": seg.cite === state.activeN ? "true" : "false",
            "aria-label": seg.cite + "번 근거로 이동",
            text: "[" + seg.cite + "]",
            onClick: function (event) { openEvidence(seg.cite, event.currentTarget); }
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
        onClick: function (event) { openEvidence(state.activeN, event.currentTarget); }
      }, [
        el("span", { class: "action-icon", "aria-hidden": "true", text: "⌗" }),
        el("span", { text: "근거 " + state.evidence.length + "개 보기" })
      ]),
      el("button", {
        type: "button",
        class: "answer-action",
        text: "검색 범위 바꾸기",
        onClick: function () { applyState({ state: "unified" }); }
      })
    ]));
    body.appendChild(el("p", {
      class: "composer-note",
      style: "text-align:left;margin:4px 0 0;",
      text: answer.note
    }));

    dom.conversation.appendChild(el("article", { class: "message assistant-message" }, [
      el("div", { class: "assistant-avatar", "aria-hidden": "true", text: "P" }),
      body
    ]));
  }

  /* Every [n] the answer cites must resolve to a record actually rendered. */
  function citationsResolve(answer, records) {
    var present = {};
    records.forEach(function (r) { present[r.n] = true; });
    var cited = Legal.evidenceNumbers(answer);
    for (var i = 0; i < cited.length; i += 1) {
      if (!present[cited[i]]) return false;
    }
    return true;
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
      text: "질문하면 공식 법률자료와 내 자료에서 근거를 찾아 출처를 붙입니다. 확인되지 않은 내용은 결론으로 제시하지 않습니다."
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
          composer.sync();
          applyState({ state: "unified" });
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
    /* Two different reasons to have no evidence, and they must not read the
     * same. "We looked and found nothing" is a result. "We could not look
     * because Drive is not connected" is a precondition failure, and offering
     * 'widen the search' there would be a dead end. */
    var driveBlocked = state.driveRequired === true || state.state === "disconnected";

    var copy = driveBlocked
      ? {
          title: "Drive 자료에 접근할 수 없습니다.",
          body: "선택한 사건의 자료가 Google Drive에 있고, 현재 이 화면에서는 Drive가 연결되어 있지 않습니다.",
          reason: "연결되지 않은 자료실은 검색 범위에 포함할 수 없습니다. 근거 없는 답변을 만들지 않고 여기서 멈춥니다.",
          badge: "DEMO · 연결 필요",
          actions: [
            { id: "widen", label: "공식 법률자료만 검색" },
            { id: "connect", label: "Google Drive 연결 (DEMO)" }
          ],
          note: "연결 전에는 내 Drive 자료를 근거로 인용할 수 없습니다."
        }
      : {
          title: Demo.FAIL_CLOSED.title,
          body: Demo.FAIL_CLOSED.body,
          reason: Demo.FAIL_CLOSED.reason,
          badge: "DEMO · 근거 없음",
          actions: Demo.FAIL_CLOSED.actions,
          note: "근거가 없는 상태에서 법률 결론을 생성하지 않는 것은 이 제품의 기본 동작입니다."
        };

    var wrap = el("div", { class: "empty-state" });

    var card = el("div", { class: "ev-empty", style: "max-width:560px;" });
    card.appendChild(el("p", { class: "ev-empty-title", style: "font-size:16px;", text: copy.title }));
    card.appendChild(el("p", { class: "ev-empty-body", text: copy.body }));
    card.appendChild(el("p", { class: "ev-empty-body", text: copy.reason }));

    var actions = el("div", { class: "ev-actions" });
    copy.actions.forEach(function (action) {
      actions.appendChild(el("button", {
        type: "button",
        class: "ev-action" + (action.id === "widen" ? " is-primary" : ""),
        text: action.label,
        onClick: function () {
          if (action.id === "widen") {
            /* Escape hatch that does NOT need Drive: official sources only. */
            applyState({ state: "official" });
          } else if (action.id === "connect") {
            applyState({ driveConnected: true, state: "drive" });
          } else {
            applyState({ state: "drive" });
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
      el("span", { class: "demo-label", text: copy.badge })
    ]));
    body.appendChild(el("div", { class: "assistant-content" }, [
      el("p", { text: copy.body })
    ]));
    wrap.appendChild(el("article", { class: "message assistant-message", style: "margin-top:22px;" }, [
      el("div", { class: "assistant-avatar", "aria-hidden": "true", text: "P" }),
      body
    ]));

    wrap.appendChild(el("p", {
      class: "composer-note",
      style: "text-align:left;margin-top:18px;",
      text: copy.note
    }));

    return wrap;
  }

  /* ── Evidence surfaces ────────────────────────────────────────────────── */
  function renderEvidence() {
    var state = store.get();
    var records = state.evidence;
    var emptyState;
    if (state.driveRequired) {
      emptyState = {
        title: "Drive 자료에 접근할 수 없습니다.",
        body: "Drive가 연결되어 있지 않아 사건 자료실의 근거를 사용할 수 없습니다.",
        reason: null
      };
    } else if (isFailClosedState(state.state)) {
      emptyState = {
        title: "표시할 근거가 없습니다.",
        body: "답변에 인용할 수 있는 근거가 확인되지 않았습니다.",
        reason: null
      };
    }

    var ctx = { activeN: state.activeN };
    /* Strongest authority first. This is the contract legal-authority.js
     * documents; it was previously never applied, so the panel showed records
     * in raw array order and a secondary source could sit above official
     * primary authority. Display order changes only — each record keeps its
     * own `n`, so the [1]/[4] markers in the answer still line up. */
    var ordered = Legal.sortEvidence(records);
    renderer.render(dom.evidenceList, ordered, ctx, emptyState);
    renderer.render(dom.drawerList, ordered, ctx, emptyState);

    dom.evidenceCount.textContent = records.length + "개";
    dom.drawerCount.textContent = records.length + "개";
    var trigger = dom.evidenceTrigger;
    trigger.querySelector(".trigger-label").textContent = "근거 " + records.length + "개";
    trigger.disabled = records.length === 0;
    trigger.setAttribute("aria-disabled", records.length === 0 ? "true" : "false");
  }

  function syncDrawer() {
    /* Belt and braces: the sheet is a mobile-only surface, so it is closed
     * unconditionally at desktop width even if state says otherwise. */
    var open = isSheetViewport() && store.get().drawerOpen;
    dom.evidenceTriggerRow.hidden = store.get().state === "home" || !isSheetViewport();
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
      "샘플 위치 '" + (record.page_or_section || "") + "' — 실제 문서 뷰어는 아직 연결되지 않았습니다.";
    openEvidence(record.n);
  }

  /* ── One responsive evidence-open path ───────────────────────────────────
   * Desktop already has a full evidence panel, so opening the bottom sheet
   * there was a second, competing surface for the same list. Citation clicks
   * now route here and the viewport decides: highlight + scroll the panel on
   * desktop, open the sheet on tablet/mobile. */
  function openEvidence(n, caller) {
    if (isSheetViewport()) {
      if (traps.drawer && caller) traps.drawer.setReturnFocus(caller);
      applyState({ activeN: n, drawerOpen: true });
      return;
    }
    if (traps.drawer) traps.drawer.setReturnFocus(null);
    applyState({ activeN: n, drawerOpen: false });
    scrollPanelToEvidence(n);
  }

  function scrollPanelToEvidence(n) {
    if (!dom.evidencePanel) return;
    var card = dom.evidencePanel.querySelector('.ev[data-evidence-n="' + n + '"]');
    if (!card) return;
    if (card.scrollIntoView) {
      card.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  /* ── State switching ──────────────────────────────────────────────────── */
  /* The store is the single source of truth. Every mutation goes through
   * store.set(), and a single subscription drives all rendering — so a handler
   * that only sets state can never leave the UI out of sync with it. */
  /* Every state change is normalised here, atomically, before it reaches the
   * store — so title, scope chip, and evidence can never disagree. Callers
   * pass only `state`; they never set scope or evidence directly. */
  function applyState(patch) {
    var next = Object.assign({}, patch);
    var state = store.get();

    /* Evidence is recomputed whenever EITHER the state or the Drive connection
     * changes. Keying it on `state` alone meant the explicit "connect" action —
     * which changes only driveConnected — left the panel stale. */
    if (next.state !== undefined || next.driveConnected !== undefined) {
      if (next.state === "disconnected") next.driveConnected = false;
      if (next.state === "home") next.drawerOpen = false;
      if (next.state === "provenance") next.activeN = 1;

      /* Recompute from the state we are moving TO and the connection state we
       * will have AFTER the move. Getting this order wrong is what let Drive
       * evidence reappear while the sidebar said "disconnected". */
      var driveAfter = next.driveConnected !== undefined
        ? next.driveConnected
        : state.driveConnected;
      var stateAfter = next.state !== undefined ? next.state : state.state;
      next.evidence = evidenceForState(stateAfter, driveAfter);
      next.driveRequired = stateAfter === "drive" && !driveAfter;
    }

    /* The bottom sheet is a mobile-only surface. Never leave it flagged open
     * on desktop, whatever the caller asked for. */
    if (!next.drawerOpen && !isSheetViewport()) next.drawerOpen = false;
    if (next.drawerOpen === true && !isSheetViewport()) next.drawerOpen = false;

    store.set(next);
    persist();
  }

  function persist() {
    try {
      var stateId = store.get().state;
      /* Guard on write as well as read, so a state that is somehow not
       * restorable can never be written in the first place. */
      if (isPersistable(stateId)) localStorage.setItem(STORAGE_KEY, stateId);
      else localStorage.removeItem(STORAGE_KEY);
    } catch (e) { /* private mode */ }
  }

  /* Restore passes ONLY a state id, so the scope chip and title are re-derived
   * the same way a fresh visit would derive them. Persisting scope separately
   * was the second place the two authorities could drift. */
  function restore() {
    var saved;
    try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) { saved = null; }
    if (saved && isPersistable(saved)) applyState({ state: saved });
  }

  function renderAll() {
    var state = store.get();
    dom.shell.setAttribute("data-view", state.state === "home" ? "home" : "conversation");
    dom.topbarTitle.textContent = titleFor(state);
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

  /* ── Sidebar drawer (mobile) ────────────────────────────────────────────
   * ONE open path and ONE close path.
   *
   * Previously the three close paths (Escape, ×, scrim) each removed the
   * class and re-synced inert/aria, but none of them called
   * traps.sidebar.close(). The drawer could therefore LOOK closed while the
   * trap was still active and its document-level keydown listener was still
   * installed — a hidden focus trap that would swallow the next Tab/Escape.
   */
  var syncing = false;

  function sidebarIsOpen() {
    return dom.shell.classList.contains("sidebar-open");
  }

  function openSidebar(caller) {
    dom.shell.classList.add("sidebar-open");
    syncSidebar();
    if (traps.sidebar) {
      if (caller) traps.sidebar.setReturnFocus(caller);
      traps.sidebar.open();
    }
  }

  function closeSidebar() {
    if (!sidebarIsOpen() && !syncing) {
      /* Even if the class is already gone, the trap may still be live from a
       * previous open. Release it unconditionally rather than by class state. */
      if (traps.sidebar && traps.sidebar.isActive()) traps.sidebar.close();
      return;
    }
    dom.shell.classList.remove("sidebar-open");
    syncSidebar();
    /* Close the trap AFTER the class is removed, so its focus restoration
     * targets the still-mounted trigger rather than a node being torn down. */
    if (traps.sidebar && traps.sidebar.isActive()) traps.sidebar.close();
  }

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
        open = false;
      }

      /* Three explicit states. The previous code derived `open` from
       * `mobile && ...` and then applied `inert = !open`, which made the
       * permanently visible DESKTOP sidebar inert — a control the user could
       * see and not use. `inert` here means "hidden behind a closed drawer",
       * never "not interactive". */
      if (!mobile) {
        dom.sidebar.inert = false;   // desktop: always interactive
        dom.mainPanel.inert = false;
      } else if (open) {
        dom.sidebar.inert = false;   // mobile open: the drawer IS the sidebar
        dom.mainPanel.inert = true;
      } else {
        dom.sidebar.inert = true;    // mobile closed: off-canvas, hide from a11y
        dom.mainPanel.inert = false;
      }

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
      composerForm: document.getElementById("composerForm"),
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
        if (actionId === "widen") applyState({ state: "unified" });
        if (actionId === "check-drive") applyState({ state: "drive" });
      }
    });

    /* Initial evidence, set before the subscription is installed so the
     * explicit renderAll() at the end of init() owns the first paint. */
    store.set({ evidence: evidenceForState("unified", store.get().driveConnected) });

    /* Demo state switcher */
    global.ClawShell.bindToggleGroup(dom.stateChips, function (value) { applyState({ state: value }); });

    /* Scope chips are re-rendered on every conversation pass, so they are bound
     * ONCE by delegation here. This is the only scope-click path; the chips
     * themselves carry no onClick. */
    dom.conversation.addEventListener("click", function (event) {
      var chip = event.target.closest('.claw-chip[data-value]');
      if (!chip) return;
      var value = chip.getAttribute("data-value");
      applyState({ state: ROUTABLE_STATES.indexOf(value) !== -1 ? value : "unified" });
    });

    /* Composer: the form submit event is the canonical send path. */
    composer = global.ClawShell.bindComposer(
      dom.composerForm, dom.composerInput, dom.sendButton, function () {
        dom.composerInput.value = "";
        composer.autosize();
        composer.sync();
        applyState({ state: "unified" });
        dom.runtimeNote.textContent = "샘플 답변을 표시했습니다. 실제 검색은 연결되지 않았습니다.";
      }
    );

    /* Drawer + sidebar traps */
    traps.drawer = global.ClawShell.createFocusTrap(dom.drawer, function () {
      applyState({ drawerOpen: false });
    });
    traps.sidebar = global.ClawShell.createFocusTrap(dom.sidebar, function () {
      closeSidebar();
    });

    dom.drawerClose.addEventListener("click", function () { applyState({ drawerOpen: false }); });
    dom.drawerScrim.addEventListener("click", function () { applyState({ drawerOpen: false }); });
    dom.evidenceTrigger.addEventListener("click", function (event) {
      if (traps.drawer) traps.drawer.setReturnFocus(event.currentTarget);
      applyState({ drawerOpen: true });
    });

    dom.panelClose.addEventListener("click", function () {
      applyState({ state: "home" });
    });

    dom.menuButton.addEventListener("click", function (event) {
      if (sidebarIsOpen()) closeSidebar();
      else openSidebar(event.currentTarget);
    });
    dom.sidebarClose.addEventListener("click", function () { closeSidebar(); });
    dom.sidebarScrim.addEventListener("click", function () { closeSidebar(); });

    dom.newResearch.addEventListener("click", function () {
      applyState({ state: "home" });
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
    /* Crossing the breakpoint while the drawer is open must release the trap
     * too, not just the class. */
    window.matchMedia("(max-width: 920px)")
      .addEventListener("change", function () {
        syncSidebar();
        if (!window.matchMedia("(max-width: 920px)").matches) closeSidebar();
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

  global.B67DemoApp = {
    store: store,
    REVIEW_STATES: REVIEW_STATES,
    STATES: REVIEW_STATES,
    PERSISTABLE_STATES: PERSISTABLE_STATES,
    isPersistable: isPersistable,
    applyState: applyState,
    evidenceForState: evidenceForState,
    scopeForState: scopeForState,
    titleForState: titleForState,
    isSheetViewport: isSheetViewport,
    openSidebar: openSidebar,
    closeSidebar: closeSidebar,
    sidebarTrap: function () { return traps.sidebar; }
  };
})(window);
