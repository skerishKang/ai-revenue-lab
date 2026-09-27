/* claw-shell.js — SHARED-LIKE (Claw) shell controller.
 *
 * Generic grounded-research shell behaviour: a tiny state store, the sidebar
 * drawer, the source-scope chip group, the composer, and the focus-management
 * helpers the drawers rely on.
 *
 * Deliberately contains NO legal concepts. It does not know what an authority
 * class, a matter, or a provenance record is. Legal wires into it through
 * B67Legal (see legal/legal-authority.js). That separation is what allows this
 * file to move into Padiem Claw unchanged.
 */
(function (global) {
  "use strict";

  /* ── Minimal state store ──────────────────────────────────────────────── */
  function createStore(initial) {
    var state = Object.assign({}, initial);
    var listeners = [];
    return {
      get: function () { return state; },
      set: function (patch) {
        var changed = false;
        Object.keys(patch).forEach(function (key) {
          if (state[key] !== patch[key]) { state[key] = patch[key]; changed = true; }
        });
        if (changed) listeners.forEach(function (fn) { fn(state, patch); });
        return state;
      },
      subscribe: function (fn) { listeners.push(fn); return function () {
        listeners = listeners.filter(function (l) { return l !== fn; });
      }; }
    };
  }

  /* ── DOM helpers ──────────────────────────────────────────────────────── */
  /* Text-only by construction: there is deliberately no `html` escape hatch.
   * Every string in this surface is sample or backend data, and an innerHTML
   * sink would make that a single markup-injection surface for no gain — no
   * caller needs it. */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "class") node.className = attrs[key];
        else if (key === "text") node.textContent = attrs[key];
        else if (key.slice(0, 2) === "on" && typeof attrs[key] === "function") {
          node.addEventListener(key.slice(2).toLowerCase(), attrs[key]);
        } else if (attrs[key] !== null && attrs[key] !== undefined && attrs[key] !== false) {
          node.setAttribute(key, attrs[key]);
        }
      });
    }
    (children || []).forEach(function (child) {
      if (child) node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  /* ── Focus management for the sidebar drawer and the evidence sheet ──────
   * Traces the canonical Claw pattern: Escape closes, focus is trapped inside
   * while open, and focus is RESTORED to the trigger on close. Restoring focus
   * is the part most easily missed and the part that matters most for keyboard
   * users.
   */
  var FOCUSABLE = [
    "a[href]", "button:not([disabled])", "input:not([disabled])",
    "select:not([disabled])", "textarea:not([disabled])", "summary", "[tabindex]:not([tabindex='-1'])"
  ].join(",");

  function focusables(root) {
    return Array.prototype.filter.call(root.querySelectorAll(FOCUSABLE), function (node) {
      return node.offsetParent !== null || node.getClientRects().length > 0;
    });
  }

  function createFocusTrap(root, onEscape) {
    var previous = null;
    var active = false;

    function onKeydown(event) {
      if (!active) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onEscape();
        return;
      }
      if (event.key !== "Tab") return;
      var items = focusables(root);
      if (items.length === 0) return;
      var first = items[0];
      var last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    return {
      open: function () {
        previous = document.activeElement;
        active = true;
        document.addEventListener("keydown", onKeydown, true);
        var items = focusables(root);
        (items[0] || root).focus();
      },
      close: function () {
        active = false;
        document.removeEventListener("keydown", onKeydown, true);
        if (previous && typeof previous.focus === "function") previous.focus();
        previous = null;
      },
      isActive: function () { return active; }
    };
  }

  /* ── Toggle-group controller (source scope chips, demo state chips) ─────
   * aria-pressed, not role=tab: a scope selection is a filter, not a view, so
   * the buttons stay in the tab order and screen readers announce pressed
   * state rather than a tab panel.
   */
  function bindToggleGroup(container, onChange) {
    if (!container) return function () {};
    var buttons = Array.prototype.slice.call(container.querySelectorAll("[data-value]"));

    function select(value) {
      buttons.forEach(function (button) {
        button.setAttribute("aria-pressed", button.getAttribute("data-value") === value ? "true" : "false");
      });
      onChange(value);
    }

    container.addEventListener("click", function (event) {
      var button = event.target.closest("[data-value]");
      if (button && container.contains(button)) select(button.getAttribute("data-value"));
    });

    return {
      select: select,
      getSelected: function () {
        var found = buttons.filter(function (b) { return b.getAttribute("aria-pressed") === "true"; });
        return found.length ? found[0].getAttribute("data-value") : null;
      }
    };
  }

  /* ── Composer wiring ───────────────────────────────────────────────────── */
  function bindComposer(input, sendButton, onSubmit) {
    if (!input || !sendButton) return;

    function autosize() {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 180) + "px";
    }

    function sync() {
      sendButton.disabled = input.value.trim() === "";
    }

    input.addEventListener("input", function () { autosize(); sync(); });
    input.addEventListener("keydown", function (event) {
      /* Enter sends, Shift+Enter newlines — the canonical chat behavior. */
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (!sendButton.disabled) onSubmit(input.value.trim());
      }
    });
    sendButton.addEventListener("click", function () {
      if (!sendButton.disabled) onSubmit(input.value.trim());
    });

    sync();
    return { autosize: autosize, sync: sync };
  }

  global.ClawShell = {
    createStore: createStore,
    el: el,
    clear: clear,
    focusables: focusables,
    createFocusTrap: createFocusTrap,
    bindToggleGroup: bindToggleGroup,
    bindComposer: bindComposer
  };
})(window);
