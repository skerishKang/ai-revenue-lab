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
      --radius-btn: 12px;
      --pad: clamp(16px, 4vw, 64px);

      /* Type and rhythm (issue #6001). One scale for every B64 surface, so a
         heading on the home page and one on the pipeline are the same size and
         a label is never small enough to strain. The values are tuned for
         Hangul: Korean needs more line-height and less negative tracking than
         Latin at the same point size, and it has no descenders to hide, so the
         display line is calmer and the small text is heavier. */
      --fs-display: clamp(26px, 4.4vw, 44px);
      --lh-display: 1.16;
      --ls-display: -.022em;
      --fs-title: 19px;
      --lh-title: 1.34;
      --fs-subtitle: 16.5px;
      --fs-body: 15px;
      --lh-body: 1.65;
      --fs-ui: 14.5px;
      --lh-ui: 1.45;
      --fs-meta: 12.5px;
      --fs-label: 12px;
      --fw-display: 700;
      --fw-title: 680;
      --fw-body: 500;
      --fw-label: 620;
      --gap-card: 12px;
      --pad-card: 18px;
      --space-section: 28px;
      --control-height: 48px;

      /* Pretendard first, per the owner's direction. It is used when installed
         and the rest of the stack is a native Korean fallback, so no webfont and
         no font-src exception is needed and the site still renders offline. */
      font-family: "Pretendard Variable", Pretendard, "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif;
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

/** Top-bar theme-toggle styles shared by both renderers. The control keeps a
 * 44×44px hit area (iOS HIG / Material minimum touch target) at every width,
 * with a clearly visible keyboard focus ring. THEME_CSS_SHELL_INSET is the
 * shared sticky-header inset: the `#top` anchor target clears the sticky
 * header when the brand link or a restored scroll lands on it. */
export const THEME_CSS_TOGGLE = `
    .theme-toggle { display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; margin-left: 8px; border-radius: 999px; border: 1px solid var(--line-soft); background: var(--surface); color: var(--muted); transition: color .16s ease, background .16s ease, border-color .16s ease; }
    .theme-toggle:hover { color: var(--text); border-color: var(--accent-border); background: var(--surface-strong); }
    .theme-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .theme-toggle__icon { display: inline-flex; width: 17px; height: 17px; }
    .theme-toggle__icon svg { width: 100%; height: 100%; }
    @media (max-width: 480px) {
      .theme-toggle { width: 44px; height: 44px; margin-left: 4px; }
    }`;

/** Shared sticky-header inset for the `#top` scroll target (issue #5822 QA). */
export const THEME_CSS_SHELL_INSET = `
    main#top { scroll-margin-top: 96px; }`;

/**
 * Category icons for the consumer screens (issue #5830). Inline SVG only —
 * no external images, fonts or scripts, so the CSP stays untouched. These
 * label the earning TYPE; they never imply provider approval or payout
 * amounts.
 */
const CATEGORY_ICONS: Readonly<Record<string, string>> = Object.freeze({
  ALL: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="2.5" y="2.5" width="6" height="6" rx="1.6" stroke="currentColor" stroke-width="1.5"/><rect x="11.5" y="2.5" width="6" height="6" rx="1.6" stroke="currentColor" stroke-width="1.5"/><rect x="2.5" y="11.5" width="6" height="6" rx="1.6" stroke="currentColor" stroke-width="1.5"/><rect x="11.5" y="11.5" width="6" height="6" rx="1.6" stroke="currentColor" stroke-width="1.5"/></svg>',
  AD_CLICK: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="2.5" y="4" width="15" height="10" rx="1.6" stroke="currentColor" stroke-width="1.5"/><path d="M10 14v3M7 17h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M6 7l2.2 1.5L6 10z" fill="currentColor"/></svg>',
  SURVEY: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 4.5h12a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.5"/><path d="M6.5 8h7M6.5 11h7M6.5 14h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  USABILITY: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M8 2.5h4a1.5 1.5 0 0 1 1.5 1.5v12A1.5 1.5 0 0 1 12 17.5H8A1.5 1.5 0 0 1 6.5 16V4A1.5 1.5 0 0 1 8 2.5Z" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="15" r="1" fill="currentColor"/><path d="M13.5 6.5c1.5.8 2.5 2 2.5 3.5s-1 2.7-2.5 3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  MICROTASK: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M11 2 4.5 11h4L9 18l6.5-9h-4L11 2Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
  SHORT_GIG: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.5"/><path d="M10 5.5V10l3 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  // Pipeline summary chips (#5830) — status visuals, not earning categories.
  IN_PROGRESS: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.5"/><path d="M10 5.5V10l3 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  COMPLETED: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.5"/><path d="M6.5 10.5l2.4 2.4 4.6-5.3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  PAID: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.5"/><path d="M6.5 10h7M10.5 7l3 3-3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  EXPECTED: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.5"/><path d="M7 12.5c.6-1 1.7-1.5 3-1.5s2.4.5 3 1.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="7.5" cy="8" r="1" fill="currentColor"/><circle cx="12.5" cy="8" r="1" fill="currentColor"/></svg>',
});

export function renderCategoryIcon(categoryId: string, className = 'category-icon'): string {
  const icon = CATEGORY_ICONS[categoryId] ?? CATEGORY_ICONS['ALL']!;
  return `<span class="${className}" aria-hidden="true">${icon}</span>`;
}

export const CATEGORY_ICON_CSS = `
    .category-icon { display: inline-flex; width: 15px; height: 15px; flex: 0 0 auto; color: var(--accent); }
    .category-icon svg { width: 100%; height: 100%; }
    .summary-icon { display: inline-flex; width: 16px; height: 16px; color: var(--faint); }
    .summary-icon svg { width: 100%; height: 100%; }`;

