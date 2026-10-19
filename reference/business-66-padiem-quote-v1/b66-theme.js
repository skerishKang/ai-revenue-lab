/* B66 appearance only. No quote, account, API or PDF state access. */
(function () {
  "use strict";
  var key = "padiem-b66-appearance-v1";
  function safeGet() { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function safeSet(value) { try { localStorage.setItem(key, value); } catch (_) { /* private browsing: session appearance still works */ } }
  function apply(value) {
    var theme = value === "dark" ? "dark" : "light";
    document.documentElement.dataset.b66Theme = theme;
    document.querySelectorAll("[data-b66-theme-choice]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.b66ThemeChoice === theme));
    });
    return theme;
  }
  apply(safeGet());
  document.addEventListener("DOMContentLoaded", function () {
    apply(safeGet());
    document.querySelectorAll("[data-b66-theme-choice]").forEach(function (button) {
      button.addEventListener("click", function () {
        var value = apply(button.dataset.b66ThemeChoice);
        safeSet(value);
      });
    });
  });
})();
