import { describe, expect, it } from "vitest";
import {
  DEFAULT_THEME,
  applyTheme,
  isThemeName,
  readThemeAttributes,
  readThemeFromLocation,
  themeSearch,
} from "../theme/theme";

/**
 * #5298 — theme contract.
 *
 * The operational product resolves its theme from the URL query and writes it
 * to `data-theme` on the document root and body. The clone keeps that contract
 * so a screenshot comparison can be taken against the operational build.
 */
describe("theme contract", () => {
  it("falls back to the operational default theme", () => {
    expect(readThemeFromLocation("")).toBe(DEFAULT_THEME);
    expect(readThemeFromLocation("?theme=nope")).toBe(DEFAULT_THEME);
    expect(readThemeFromLocation("?theme=dark")).toBe("dark");
  });

  it("recognises only the operational theme names", () => {
    expect(isThemeName("padiem-glass")).toBe(true);
    expect(isThemeName("padiem-glass-2")).toBe(false);
    expect(isThemeName(null)).toBe(false);
  });

  it("reads the glass variant, mask and speed attributes", () => {
    const attributes = readThemeAttributes("?theme=dark&glass=male&mask=on&speed=200");
    expect(attributes).toEqual({
      theme: "dark",
      variant: "male",
      mask: "on",
      speed: 200,
    });
  });

  it("rejects an out-of-range glass speed", () => {
    expect(readThemeAttributes("?speed=5000").speed).toBe(100);
    expect(readThemeAttributes("?speed=10").speed).toBe(100);
  });

  it("writes the theme attributes onto the document", () => {
    applyTheme({
      theme: "cinematic",
      variant: "female",
      mask: "auto",
      speed: 100,
    });
    expect(document.documentElement).toHaveAttribute("data-theme", "cinematic");
    expect(document.documentElement).toHaveAttribute("data-glass-variant", "female");
    expect(document.documentElement).toHaveAttribute("data-glass-mask", "auto");
    expect(document.documentElement).toHaveAttribute("data-glass-speed", "100");
    expect(document.body).toHaveAttribute("data-theme", "cinematic");
  });

  it("keeps the theme in the URL query only", () => {
    const search = themeSearch({
      theme: "light",
      variant: "female",
      mask: "auto",
      speed: 100,
    });
    expect(search).toContain("theme=light");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});
