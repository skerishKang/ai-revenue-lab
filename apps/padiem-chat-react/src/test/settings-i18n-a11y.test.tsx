import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { LocaleProvider } from "../i18n/LocaleProvider";
import { locale } from "../lib/locale";

/** The app is always used inside the language provider. */
function renderApp() {
  return render(
    <LocaleProvider>
      <App />
    </LocaleProvider>,
  );
}

/**
 * #5298 — settings, language and accessibility.
 *
 * The language lives in the URL and in the document language attribute, and
 * the copy comes from the product's own dictionary. The settings surface uses
 * the product's structure so the approved styling applies unchanged.
 */
describe("React clone settings, language and accessibility", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "content-type": "application/json" },
        });
      if (url.includes("/api/auth/status")) {
        return json({
          ready: false,
          authenticated: false,
          history_ready: false,
          user: null,
          model_requires_session: true,
          session_state: "unavailable",
          methods: {},
        });
      }
      return json({ error: { code: "not_found", message: "not found" } }, 404);
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    window.history.replaceState(null, "", "/");
  });

  it("opens the settings surface from the sidebar and offers the product's themes", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(document.getElementById("settingsButton") as HTMLElement);

    await waitFor(() => {
      expect(document.getElementById("settingsDialog")).toBeInTheDocument();
    });
    const themeValues = [...document.querySelectorAll("#themePicker .theme-option")].map(
      (option) => option.getAttribute("data-theme-value"),
    );
    expect(themeValues).toEqual([
      "light",
      "dark",
      "cinematic",
      "padiem-home",
      "padiem-glass",
    ]);
    const languageValues = [...document.querySelectorAll("#languagePicker .language-option")].map(
      (option) => option.getAttribute("data-locale-value"),
    );
    expect(languageValues).toEqual(["ko", "en"]);
  });

  it("switches the language with the product's dictionary and keeps it in the URL", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(document.getElementById("settingsButton") as HTMLElement);
    await user.click(document.querySelector('[data-locale-value="en"]') as HTMLElement);

    await waitFor(() => {
      expect(document.documentElement.lang).toBe("en");
    });
    expect(window.location.search).toContain("lang=en");
    // The copy comes from the product's own English dictionary.
    expect(screen.getByRole("button", { name: /Theme/i })).toBeInTheDocument();
    expect(locale.getCurrent()).toBe("en");

    // The language switch is reversible and the product's copy is used.
    await user.click(document.querySelector('[data-locale-value="ko"]') as HTMLElement);
    await waitFor(() => {
      expect(document.documentElement.lang).toBe("ko");
    });
    expect(screen.getByRole("button", { name: /테마/ })).toBeInTheDocument();
  });

  it("closes the settings dialog with Escape and returns the focus to the trigger", async () => {
    const user = userEvent.setup();
    renderApp();

    const trigger = document.getElementById("settingsButton") as HTMLElement;
    await user.click(trigger);
    await waitFor(() => {
      expect(document.getElementById("settingsDialog")).toBeInTheDocument();
    });

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(document.getElementById("settingsDialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger);
    });
  });

  it("keeps the closed drawer inert on a phone and closes it with Escape", async () => {
    const user = userEvent.setup();
    // The drawer rules only apply on a phone viewport.
    (window as unknown as { __matchMedia?: (q: string) => boolean }).__matchMedia = (query) =>
      query.includes("920px");
    renderApp();

    const sidebar = document.getElementById("sidebar") as HTMLElement;
    const mainPanel = document.querySelector(".main-panel") as HTMLElement;
    const menu = document.getElementById("mobileMenu") as HTMLElement;
    const scrim = document.getElementById("sidebarScrim") as HTMLElement;

    // A closed drawer is inert and the scrim is hidden.
    expect(sidebar.inert).toBe(true);
    expect(mainPanel.inert).toBe(false);
    expect(scrim.hidden).toBe(true);
    expect(menu.getAttribute("aria-expanded")).toBe("false");

    await user.click(menu);
    await waitFor(() => {
      expect(document.querySelector(".app-shell")?.classList.contains("sidebar-open")).toBe(true);
    });
    // An open drawer makes the main panel inert.
    expect(mainPanel.inert).toBe(true);
    expect(sidebar.inert).toBe(false);
    expect(menu.getAttribute("aria-expanded")).toBe("true");

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(document.querySelector(".app-shell")?.classList.contains("sidebar-open")).toBe(false);
    });
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(sidebar.inert).toBe(true);
  });
});
