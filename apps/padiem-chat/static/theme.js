(() => {
  "use strict";
  const VALID = ["padiem-home", "light", "dark", "cinematic"];
  const COLORS = { light: "#f8f8fb", dark: "#0b0c0e", cinematic: "#06080d", "padiem-home": "#e6e9ee" };
  const SCHEMES = { light: "light", dark: "dark", cinematic: "dark", "padiem-home": "light" };
  const valid = (value) => VALID.includes(value);
  const apply = (theme) => {
    if (!valid(theme)) return;
    document.documentElement.dataset.theme = theme;
    document.body?.setAttribute("data-theme", theme);
    document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", SCHEMES[theme]);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", COLORS[theme]);
    document.querySelectorAll("[data-theme-value]").forEach((button) => {
      const active = button.dataset.themeValue === theme;
      button.setAttribute("aria-pressed", String(active));
      if (active) button.setAttribute("aria-current", "true"); else button.removeAttribute("aria-current");
    });
    window.dispatchEvent(new CustomEvent("padiem:themechange", { detail: { theme } }));
  };
  const init = () => {
    const theme = document.documentElement.dataset.theme;
    apply(valid(theme) ? theme : "padiem-home");
    const picker = document.getElementById("themePicker");
    picker?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-theme-value]");
      if (button) apply(button.dataset.themeValue);
    });
  };
  window.__padiemTheme = { VALID, apply, getCurrent: () => document.documentElement.dataset.theme };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
