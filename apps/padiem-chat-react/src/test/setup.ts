import "@testing-library/jest-dom/vitest";

/**
 * The media query list.
 *
 * jsdom does not implement `matchMedia`. The product's own accessibility
 * module and the clone's drawer rules use it, so the test environment
 * provides it instead of the product changing.
 */
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: Boolean(
      (window as unknown as { __matchMedia?: (q: string) => boolean }).__matchMedia?.(query),
    ),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

/**
 * The native dialog modal API.
 *
 * jsdom does not implement `showModal()` / `close()`. The product's own
 * confirm dialog and the clone's modal surfaces use them, so the test
 * environment provides the same behaviour instead of the product changing.
 */
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
    this.setAttribute("aria-modal", "true");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.removeAttribute("aria-modal");
    this.dispatchEvent(new Event("close"));
  };
}
