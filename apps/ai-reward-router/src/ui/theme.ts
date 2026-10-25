/**
 * B64 consumer theme (issue #5822, parent #987).
 *
 * Light is the default theme; the user can switch to the existing dark
 * design and the choice persists across navigation and reloads.
 *
 * The consumer surface runs under `script-src 'none'`, so the toggle is a
 * plain same-origin link: the server reads the `b64_theme` cookie, re-renders
 * with `<html data-theme="…">` driven CSS custom properties, and the toggle
 * link sets the opposite theme via a 303 redirect. No script is added and
 * the CSP is untouched. The preference lives in a `HttpOnly; SameSite=Lax;
 * Secure` cookie — an explicit user choice wins over OS color-scheme hints
 * (the owner decision is "first visit defaults to Light").
 */

export type B64Theme = 'light' | 'dark';

export const THEME_COOKIE_NAME = 'b64_theme';
export const THEME_QUERY_PARAM = 'theme';
export const THEME_TOGGLE_VALUE = 'toggle';
export const THEME_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

export const DEFAULT_THEME: B64Theme = 'light';

export function isB64Theme(value: unknown): value is B64Theme {
  return value === 'light' || value === 'dark';
}

export function toggleTheme(theme: B64Theme): B64Theme {
  return theme === 'light' ? 'dark' : 'light';
}

/** Reads the persisted theme; anything other than a stored choice is Light. */
export function readThemeFromCookie(cookieHeader: string | null | undefined): B64Theme {
  if (!cookieHeader) return DEFAULT_THEME;
  let found: string | null = null;
  for (const part of cookieHeader.split(';')) {
    const separator = part.indexOf('=');
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() !== THEME_COOKIE_NAME) continue;
    found = part.slice(separator + 1).trim();
  }
  return isB64Theme(found) ? found : DEFAULT_THEME;
}

/** Set-Cookie value for the persisted theme choice. */
export function themeCookieHeaderValue(theme: B64Theme): string {
  return [
    `${THEME_COOKIE_NAME}=${theme}`,
    'Path=/',
    `Max-Age=${THEME_COOKIE_MAX_AGE_SECONDS}`,
    'HttpOnly',
    'SameSite=Lax',
    'Secure',
  ].join('; ');
}

/** True when this GET request is a theme-toggle link following. */
export function isThemeToggleRequest(url: URL): boolean {
  return url.searchParams.get(THEME_QUERY_PARAM) === THEME_TOGGLE_VALUE;
}

/**
 * Toggle-link target for the current route: same path and query with only
 * the theme parameter switched to the toggle marker, so filters/categories
 * survive a theme switch.
 */
export function themeToggleHref(pathname: string, searchParams: URLSearchParams): string {
  const params = new URLSearchParams(searchParams);
  params.set(THEME_QUERY_PARAM, THEME_TOGGLE_VALUE);
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

const SUN_ICON = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="4" fill="currentColor"/><g stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M3.9 3.9l1.4 1.4M14.7 14.7l1.4 1.4M16.1 3.9l-1.4 1.4M5.3 14.7l-1.4 1.4"/></g></svg>';
const MOON_ICON = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M16.5 12.2A7 7 0 0 1 7.8 3.5a7 7 0 1 0 8.7 8.7Z" fill="currentColor"/></svg>';

/**
 * The sun/moon toggle shown in the top bar of every consumer screen. It is a
 * keyboard-focusable link (no script); the icon announces the theme the user
 * will switch TO, and the accessible name says the same.
 */
export function renderThemeToggleButton(currentTheme: B64Theme, href: string): string {
  const target = toggleTheme(currentTheme);
  const targetLabel = target === 'dark' ? '다크 테마로 전환' : '라이트 테마로 전환';
  const icon = target === 'dark' ? MOON_ICON : SUN_ICON;
  return `<a class="theme-toggle" href="${escapeHtml(href)}" aria-label="${targetLabel}" title="${targetLabel}"><span class="theme-toggle__icon" aria-hidden="true">${icon}</span></a>`;
}

/**
 * Shared CSS custom properties for both consumer renderers. Light values are
 * the `:root` default; the existing dark design is preserved verbatim as the
 * `html[data-theme="dark"]` override. Renderer-specific variables (gradients,
 * status colors) live here too so neither page hardcodes theme colors.
 */
export const THEME_CSS_VARIABLES = `
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --bg-soft: #eef1f7;
      --bg-glow: radial-gradient(1100px 480px at 50% -120px, rgba(26,111,209,.07), transparent 62%);
      --surface: #ffffff;
      --surface-strong: #f2f6fc;
      --line: #c9d3e3;
      --line-soft: #dde4ef;
      --text: #17233b;
      --muted: #46536e;
      --faint: #6e7b95;
      --accent: #1a6fd1;
      --accent-strong: #155fa8;
      --accent-dim: rgba(26,111,209,.10);
      --accent-border: rgba(26,111,209,.32);
      --accent-border-hover: rgba(26,111,209,.55);
      --on-accent: #ffffff;
      --gold: #8f6312;
      --gold-dim: rgba(143,99,18,.10);
      --gold-border: rgba(143,99,18,.34);
      --success: #147a48;
      --success-dim: rgba(20,122,72,.12);
      --success-border: rgba(20,122,72,.34);
      --danger: #b3352f;
      --danger-dim: rgba(179,53,47,.10);
      --danger-border: rgba(179,53,47,.34);
      --topbar-bg: rgba(245,247,251,.86);
      --card-bg: linear-gradient(180deg, #ffffff, #f9fbfe);
      --card-bg-hover: linear-gradient(180deg, #ffffff, #f2f6fc);
      --brand-glow: drop-shadow(0 0 10px rgba(26,111,209,.18));
      --ghost-hover-bg: rgba(26,111,209,.06);
      --radius-card: 16px;
      --radius-btn: 10px;
      --pad: clamp(16px, 4vw, 64px);
      font-family: "SUIT Variable", "SUIT", "Pretendard", "Apple SD Gothic Neo", system-ui, sans-serif;
      font-synthesis: none;
      text-rendering: optimizeLegibility;
      -webkit-font-smoothing: antialiased;
    }
    html[data-theme="dark"] {
      color-scheme: dark;
      --bg: #06080d;
      --bg-soft: #0b0f16;
      --bg-glow: radial-gradient(1100px 480px at 50% -120px, rgba(136,201,255,.075), transparent 62%);
      --surface: rgba(255,255,255,.055);
      --surface-strong: rgba(255,255,255,.105);
      --line: rgba(255,255,255,.14);
      --line-soft: rgba(255,255,255,.09);
      --text: #f4f6fb;
      --muted: rgba(255,255,255,.68);
      --faint: rgba(255,255,255,.45);
      --accent: #88c9ff;
      --accent-strong: #5fb3ff;
      --accent-dim: rgba(136,201,255,.14);
      --accent-border: rgba(136,201,255,.25);
      --accent-border-hover: rgba(136,201,255,.4);
      --on-accent: #06080d;
      --gold: #efc984;
      --gold-dim: rgba(239,201,132,.14);
      --gold-border: rgba(239,201,132,.32);
      --success: #64dc82;
      --success-dim: rgba(100,220,130,.14);
      --success-border: rgba(100,220,130,.32);
      --danger: #ff6464;
      --danger-dim: rgba(255,100,100,.14);
      --danger-border: rgba(255,100,100,.32);
      --topbar-bg: rgba(6,8,13,.78);
      --card-bg: linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.045));
      --card-bg-hover: linear-gradient(180deg, rgba(255,255,255,.09), rgba(255,255,255,.05));
      --brand-glow: drop-shadow(0 0 12px rgba(136,201,255,.25));
      --ghost-hover-bg: rgba(255,255,255,.04);
    }`;

/** Top-bar theme-toggle styles shared by both renderers. */
export const THEME_CSS_TOGGLE = `
    .theme-toggle { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; margin-left: 8px; border-radius: 999px; border: 1px solid var(--line-soft); background: var(--surface); color: var(--muted); transition: color .16s ease, background .16s ease, border-color .16s ease; }
    .theme-toggle:hover { color: var(--text); border-color: var(--accent-border); background: var(--surface-strong); }
    .theme-toggle__icon { display: inline-flex; width: 17px; height: 17px; }
    .theme-toggle__icon svg { width: 100%; height: 100%; }`;
