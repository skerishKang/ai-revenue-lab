/* claw-evidence.js — SHARED-LIKE (Claw) evidence card renderer.
 *
 * Renders the generic "grounded answer → numbered source → open the original"
 * card. This is the same primitive Padiem Chat already ships as
 * `.answer-sources`, promoted to a first-class desktop panel and mobile sheet.
 *
 * THE SEAM
 * `renderer.setDecorator(fn)` is the single extension point. The generic card
 * knows how to draw a numbered, titled, meta-tagged, quotable, openable card.
 * It does NOT know what an "authority class" or a "provenance record" is — a
 * decorator supplies that. Legal supplies its decorator in
 * legal/legal-evidence-provenance.js; a non-legal Claw surface (e.g. a
 * product-research surface) can supply a different one and reuse every line
 * of this file.
 */
(function (global) {
  "use strict";

  var el = global.ClawShell.el;

  function createRenderer(options) {
    var opts = options || {};
    var decorator = opts.decorator || function (record, ctx) { return null; };
    var onOpen = opts.onOpen || function () {};
    var onLocator = opts.onLocator || function () {};

    function metaRow(label, value) {
      if (value === undefined || value === null || String(value).trim() === "") return null;
      return el("div", null, [
        el("dt", { text: label }),
        el("dd", { text: String(value) })
      ]);
    }

    /* Generic card. Fields read here are the intersection every grounded
     * source has: an ordinal, a title, an origin document, a couple of
     * labelled facts, an optional quote, and an action to open the original. */
    function card(record, ctx) {
      var decorations = decorator(record, ctx || {});
      var node = el("li", {
        class: "ev",
        "data-evidence-n": record.n,
        "data-active": ctx && ctx.activeN === record.n ? "true" : "false"
      });

      /* Classification attributes come from the decorator, not from this file.
       * A surface that does not classify anything simply returns none and the
       * card stays neutral — which is what lets a non-legal Claw surface reuse
       * this card verbatim. */
      (decorations.attrs || []).forEach(function (pair) {
        node.setAttribute(pair[0], pair[1]);
      });

      var head = el("div", { class: "ev-head" }, [
        el("span", { class: "ev-num", text: "[" + record.n + "]", "aria-hidden": "true" })
      ]);

      /* Decorator may contribute the authority badge / source chip into the
       * card head. This is the only place the generic card is extended. */
      (decorations.head || []).forEach(function (d) { head.appendChild(d); });

      node.appendChild(head);
      node.appendChild(el("p", { class: "ev-title", text: record.title || "(제목 없음)" }));

      if (record.document_id) {
        node.appendChild(el("p", { class: "ev-doc", text: record.document_id }));
      }

      /* Decorator may contribute the structured provenance block. */
      (decorations.body || []).forEach(function (d) { node.appendChild(d); });

      /* Generic meta: only the facts a grounded source always has. */
      var meta = el("dl", { class: "ev-meta" });
      [
        metaRow("출처", record.source_type ? (opts.sourceTypeLabel || function (t) { return t; })(record.source_type) : null),
        metaRow("위치", record.page_or_section || null),
        metaRow("확인 시각", record.retrieved_at || null),
        metaRow("버전", record.effective_date_or_version || null)
      ].forEach(function (row) { if (row) meta.appendChild(row); });
      if (meta.childNodes.length) node.appendChild(meta);

      if (record.quote) {
        node.appendChild(el("blockquote", { class: "ev-quote", text: record.quote }));
      }

      var actions = el("div", { class: "ev-actions" });
      if (record.url_or_drive_ref) {
        actions.appendChild(el("button", {
          type: "button",
          class: "ev-action is-primary",
          onClick: function () { onOpen(record); }
        }, [
          el("span", { class: "action-icon", "aria-hidden": "true", text: "↗" }),
          el("span", { text: opts.openLabel || "원문 열기" })
        ]));
      }
      if (record.page_or_section) {
        actions.appendChild(el("button", {
          type: "button",
          class: "ev-action",
          onClick: function () { onLocator(record); }
        }, [
          el("span", { class: "action-icon", "aria-hidden": "true", text: "⌖" }),
          el("span", { text: record.locator_action || "위치로 이동" })
        ]));
      }
      (decorations.actions || []).forEach(function (a) { actions.appendChild(a); });
      if (actions.childNodes.length) node.appendChild(actions);

      return node;
    }

    /* Generic empty state. The copy is supplied by the caller because whether
     * this is a "no results" or a "failed closed" message is a domain
     * decision — for Legal it is the latter, and it must say so. */
    function emptyCard(state) {
      return el("li", { class: "ev-empty" }, [
        el("p", { class: "ev-empty-title", text: state.title }),
        el("p", { class: "ev-empty-body", text: state.body }),
        state.reason ? el("p", { class: "ev-empty-body", text: state.reason }) : null
      ]);
    }

    function render(listNode, records, ctx, emptyState) {
      global.ClawShell.clear(listNode);
      if (!records || records.length === 0) {
        if (emptyState) {
          listNode.appendChild(emptyCard(emptyState));
          if (emptyState.actions && emptyState.actions.length) {
            var group = el("div", { class: "ev-actions" });
            emptyState.actions.forEach(function (action) {
              group.appendChild(el("button", {
                type: "button",
                class: "ev-action" + (action.primary ? " is-primary" : ""),
                text: action.label,
                onClick: function () { if (opts.onEmptyAction) opts.onEmptyAction(action.id); }
              }));
            });
            listNode.appendChild(group);
          }
        } else {
          listNode.appendChild(el("li", { class: "ev-empty" }, [
            el("p", { class: "ev-empty-body", text: "표시할 근거가 없습니다." })
          ]));
        }
        return;
      }
      records.forEach(function (record) { listNode.appendChild(card(record, ctx)); });
    }

    return {
      render: render,
      card: card,
      setDecorator: function (fn) { decorator = fn || decorator; }
    };
  }

  global.ClawEvidence = { createRenderer: createRenderer };
})(window);
