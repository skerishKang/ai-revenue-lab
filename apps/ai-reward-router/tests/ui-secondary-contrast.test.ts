import test from 'node:test';
import assert from 'node:assert/strict';
import { THEME_CSS_VARIABLES } from '../src/ui/theme.js';

/**
 * #5822 ships Light and Dark across every consumer screen; the completion bar
 * includes 대비. The secondary text tokens — `--faint` (verification dates,
 * disclaimers, the "미확인" state) and the immediate tier chip — measured below
 * WCAG 2.2 AA on the surfaces they actually sit on: 3.97 and 4.48. Those strings
 * are the ones that keep B64 from over-claiming, so they are not decoration.
 *
 * This test computes the ratios from the shipped tokens rather than matching
 * colour literals, so a later restyle that reintroduces a low-contrast pair
 * fails here with the number attached.
 */

type RGBA = [number, number, number, number];

function parseColor(value: string): RGBA | null {
  const hex = value.match(/^#([0-9a-f]{6})$/i)?.[1];
  if (hex) {
    return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16), 1];
  }
  const fn = value.match(/rgba?\(([^)]+)\)/)?.[1];
  if (!fn) return null;
  const parts = fn.split(/[\s,/]+/).filter(Boolean).map(Number);
  const [r, g, b, a] = parts;
  if (r === undefined || g === undefined || b === undefined) return null;
  return [r, g, b, a === undefined ? 1 : a];
}

function over(fg: RGBA, bg: RGBA): RGBA {
  return [
    fg[0] * fg[3] + bg[0] * (1 - fg[3]),
    fg[1] * fg[3] + bg[1] * (1 - fg[3]),
    fg[2] * fg[3] + bg[2] * (1 - fg[3]),
    1,
  ];
}

function luminance(c: RGBA): number {
  const channel = [c[0], c[1], c[2]].map((v) => {
    const x = v / 255;
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channel[0]! + 0.7152 * channel[1]! + 0.0722 * channel[2]!;
}

function ratio(fg: RGBA, bg: RGBA): number {
  const a = luminance(fg);
  const b = luminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function block(selector: string): string {
  const start = THEME_CSS_VARIABLES.indexOf(selector);
  assert.ok(start >= 0, `${selector} must exist in the shipped theme`);
  const open = THEME_CSS_VARIABLES.indexOf('{', start);
  return THEME_CSS_VARIABLES.slice(open + 1, THEME_CSS_VARIABLES.indexOf('}', open));
}

function token(name: string, css: string): RGBA {
  const raw = css.match(new RegExp(name.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&') + ':\\s*([^;]+);'))?.[1]?.trim();
  assert.ok(raw, `${name} missing from the theme block`);
  const parsed = parseColor(raw);
  assert.ok(parsed, `${name} value ${raw} is not a colour this audit can score`);
  return parsed;
}

/** Stack a translucent token the way the browser composites it. */
function resolve(name: string, css: string, base: RGBA): RGBA {
  const c = token(name, css);
  return c[3] < 1 ? over(c, base) : c;
}

function assertAA(label: string, fg: RGBA, bg: RGBA, minimum = 4.5): void {
  const value = Math.round(ratio(fg, bg) * 100) / 100;
  assert.ok(value >= minimum, `${label}: ${value}:1 is below the ${minimum}:1 AA requirement`);
}

for (const [theme, selector] of [['light', ':root'], ['dark', 'html[data-theme="dark"]']] as const) {
  test(`${theme}: secondary text clears WCAG AA on the surfaces it actually sits on`, () => {
    const css = block(selector);
    const page = resolve('--bg', css, [255, 255, 255, 1]);
    const card = resolve('--surface', css, page);
    const worst = luminance(card) > luminance(page) ? card : page;

    assertAA(`${theme} --faint on the tighter of card/page`, resolve('--faint', css, card), worst);
    assertAA(`${theme} --muted on card`, resolve('--muted', css, card), card);
    assertAA(`${theme} --text on page`, resolve('--text', css, page), page, 7);
  });
}

test('the immediate tier chip keeps its tint and clears AA', () => {
  const css = block(':root');
  const card = resolve('--surface', css, resolve('--bg', css, [255, 255, 255, 1]));
  const chipBg = over(resolve('--accent-dim', css, card), card);
  const strong = resolve('--accent-strong', css, card);
  assertAA('tier chip label on its tinted background', strong, chipBg);
});

test('the gold reward figure stays readable', () => {
  const css = block(':root');
  const card = resolve('--surface', css, resolve('--bg', css, [255, 255, 255, 1]));
  assertAA('light --gold on card', resolve('--gold', css, card), card, 3);
});
