/**
 * #5298 — theme contract.
 *
 * The operational product resolves its theme from the URL query and writes it
 * to `data-theme` on `<html>` and `<body>` (see
 * `apps/padiem-chat/static/theme.js` and `theme-init.js`). The clone keeps
 * the same attribute contract and the same theme names so a screenshot
 * comparison can be taken against the operational build.
 */

export const THEME_NAMES = [
  "light",
  "dark",
  "cinematic",
  "padiem-home",
  "padiem-glass",
] as const;

export type ThemeName = (typeof THEME_NAMES)[number];

export const DEFAULT_THEME: ThemeName = "padiem-glass";

export const THEME_LABELS: Record<ThemeName, string> = {
  light: "Light",
  dark: "Dark",
  cinematic: "Cinematic",
  "padiem-home": "Padiem Home",
  "padiem-glass": "Padiem Glass",
};

export const GLASS_VARIANTS = ["female", "male"] as const;
export type GlassVariant = (typeof GLASS_VARIANTS)[number];

export const GLASS_MASKS = ["auto", "on", "off"] as const;
export type GlassMask = (typeof GLASS_MASKS)[number];

const THEME_COLORS: Record<ThemeName, string> = {
  light: "#f8f8fb",
  dark: "#131417",
  cinematic: "#04070d",
  "padiem-home": "#e6e9ee",
  "padiem-glass": "#aeb6bf",
};

export function isThemeName(value: string | null | undefined): value is ThemeName {
  return typeof value === "string" && (THEME_NAMES as readonly string[]).includes(value);
}

export function readThemeFromLocation(search: string): ThemeName {
  const theme = new URLSearchParams(search).get("theme");
  return isThemeName(theme) ? theme : DEFAULT_THEME;
}

export interface ThemeAttributes {
  theme: ThemeName;
  variant: GlassVariant;
  mask: GlassMask;
  speed: number;
}

export function readThemeAttributes(search: string): ThemeAttributes {
  const params = new URLSearchParams(search);
  const variant = params.get("glass");
  const mask = params.get("mask");
  const speed = Number.parseInt(params.get("speed") ?? "", 10);
  return {
    theme: readThemeFromLocation(search),
    variant:
      variant === "male" || variant === "female"
        ? variant
        : "female",
    mask: mask === "on" || mask === "off" || mask === "auto" ? mask : "auto",
    speed: Number.isFinite(speed) && speed >= 20 && speed <= 300 ? speed : 100,
  };
}

/**
 * Writes the theme attributes onto the document root and body. The operational
 * product sets the same attributes, so every operational stylesheet selector
 * such as `html[data-theme="padiem-glass"]` resolves identically here.
 */
export function applyTheme(attributes: ThemeAttributes): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.setAttribute("data-theme", attributes.theme);
  root.setAttribute("data-glass-variant", attributes.variant);
  root.setAttribute("data-glass-mask", attributes.mask);
  root.setAttribute("data-glass-speed", String(attributes.speed));
  root.style.colorScheme =
    attributes.theme === "light" ||
    attributes.theme === "padiem-home" ||
    attributes.theme === "padiem-glass"
      ? "light"
      : "dark";
  if (document.body) {
    document.body.setAttribute("data-theme", attributes.theme);
    document.body.setAttribute("data-glass-variant", attributes.variant);
    document.body.setAttribute("data-glass-mask", attributes.mask);
    document.body.setAttribute("data-glass-speed", String(attributes.speed));
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", THEME_COLORS[attributes.theme] ?? "#04070d");
  }
}

/**
 * The operational product keeps the theme in the URL query only — it stores
 * nothing in browser storage. The clone mirrors that so a reload reproduces
 * the same view without leaving state behind.
 */
export function themeSearch(attributes: ThemeAttributes): string {
  const params = new URLSearchParams();
  params.set("theme", attributes.theme);
  params.set("glass", attributes.variant);
  params.set("mask", attributes.mask);
  params.set("speed", String(attributes.speed));
  return `?${params.toString()}`;
}
