// Brand skin for the common PADIEM login screen.
//
// The brand is chosen only from the registered client_id the auth Worker has
// already validated; there is no separate `service` parameter to choose a skin.
// A client without an entry here keeps the plain PADIEM screen. The design is
// the approved LoveTree night/garden auth skin (lovetree-4.0 PR #208; the
// four orbit photos and their size/opacity tokens follow #347). The
// heading/lead come from the brand table and the small fixed line states that
// this is a PADIEM account, in both languages.
import { AUTH_SKIN_ASSETS } from './skin-assets.mjs';
import { signupCompleteBody, signupCompleteRefresh, signupCompleteText } from './signup-complete.mjs';

export const AUTH_SKIN_ASSET_PREFIX = '/assets/auth-skin/';

export const AUTH_BRANDS = Object.freeze({
  'lovetree-4-0': Object.freeze({
    id: 'lovetree-4-0',
    wordmark: 'LoveTree',
    wordmarkSuffix: '4.1',
    defaultTheme: 'night',
    strings: Object.freeze({
      ko: Object.freeze({
        loginTitle: 'LoveTree에 로그인',
        signupTitle: '이메일로 회원가입',
        eyebrow: 'PADIEM 계정',
        google: 'Google 계정으로 계속',
        divider: '또는 이메일로',
        email: '이메일',
        password: '비밀번호',
        name: '이름',
        optional: '선택',
        loginSubmit: '이메일로 로그인',
        signupSubmit: '회원가입',
        loginAlt: '이메일로 회원가입',
        signupAlt: '이메일로 로그인',
        completeAction: 'LoveTree로 돌아가기',
      }),
      en: Object.freeze({
        loginTitle: 'Sign in to LoveTree',
        signupTitle: 'Create your account',
        eyebrow: 'PADIEM account',
        google: 'Continue with Google',
        divider: 'or with email',
        email: 'Email',
        password: 'Password',
        name: 'Name',
        optional: 'optional',
        loginSubmit: 'Sign in with email',
        signupSubmit: 'Create account',
        loginAlt: 'Create an account with email',
        signupAlt: 'Sign in with email',
        completeAction: 'Return to LoveTree',
      }),
    }),
  }),
});

const ACCOUNT_LINE = Object.freeze({
  ko: 'PADIEM 계정으로 로그인합니다 · 하나의 계정으로 PADIEM 서비스를 이용할 수 있어요',
  en: 'Signing in with a PADIEM account · One account works across PADIEM services',
});

export function resolveBrand(clientId) {
  return typeof clientId === 'string' && Object.prototype.hasOwnProperty.call(AUTH_BRANDS, clientId)
    ? AUTH_BRANDS[clientId]
    : null;
}

// Only a registered brand gets a themed skin; anything other than the two
// documented values falls back to the brand's night tokens.
export function resolveTheme(brand, requested) {
  if (!brand) return '';
  return String(requested ?? '').toLowerCase() === 'garden' ? 'garden' : brand.defaultTheme;
}

export function resolveLang(acceptLanguage) {
  const header = String(acceptLanguage ?? '').toLowerCase();
  if (!header) return 'ko';
  const ranked = header.split(',').map((part) => {
    const [tag, ...params] = part.trim().split(';');
    const weight = params.map((p) => p.trim()).find((p) => p.startsWith('q='));
    const q = weight ? Number(weight.slice(2)) : 1;
    return { tag: tag.trim(), q: Number.isFinite(q) ? q : 0 };
  }).filter((x) => x.tag && x.q > 0).sort((a, b) => b.q - a.q);
  for (const { tag } of ranked) {
    const primary = tag.split('-')[0];
    if (primary === 'en') return 'en';
    if (primary === 'ko') return 'ko';
  }
  return 'ko';
}

export function padiemAccountLine(lang) {
  return ACCOUNT_LINE[lang === 'en' ? 'en' : 'ko'];
}

const esc = (value) => String(value)
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

const decoded = new Map();

export function authSkinAsset(name) {
  const asset = AUTH_SKIN_ASSETS[name];
  if (!asset) return null;
  if (!decoded.has(name)) {
    decoded.set(name, Uint8Array.from(atob(asset.base64), (c) => c.charCodeAt(0)));
  }
  return { type: asset.type, bytes: decoded.get(name) };
}

export const AUTH_SKIN_CSS = `
@font-face{font-family:'Gowun Batang';font-style:normal;font-weight:700;font-display:swap;src:url('/assets/auth-skin/fonts/GowunBatang-Bold.latin.woff2') format('woff2')}
@font-face{font-family:'Roboto';font-style:normal;font-weight:500;font-display:swap;src:url('/assets/auth-skin/fonts/Roboto-Medium.latin.woff2') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Roboto';font-style:normal;font-weight:500;font-display:swap;src:url('/assets/auth-skin/fonts/Roboto-Medium.latin-ext.woff2') format('woff2');unicode-range:U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C4,U+2113,U+2C60-2C7F,U+A720-A7FF}
:root{--lt-ui:system-ui,-apple-system,'Segoe UI','Malgun Gothic','Apple SD Gothic Neo',sans-serif;--lt-reading:'Gowun Batang','Noto Serif CJK KR',Batang,serif;--lt-stage:#040407;--lt-stage-2:#0a0a11;--lt-pearl:#f5f1e9;--lt-muted:#9b98a6;--lt-gold:#ffe6a6;--lt-gold-deep:#e6b14c;--lt-gold-line:rgba(255,230,166,.45);--lt-gold-glow:rgba(238,190,104,.68);--lt-rose-ink:#bd5d72;--lt-paper:#f5efe2;--lt-ink:#433a34;--lt-glass-strong:rgba(7,7,12,.9);--lt-line:rgba(255,255,255,.14);--lt-primary:#eee9e0;--lt-primary-ink:#0a090d;--lt-r-pill:999px;--lt-r-panel:22px;--lt-garden-shadow:0 18px 40px rgba(75,51,42,.16);--lt-google-fill:#131314;--lt-google-stroke:#8e918f;--lt-google-font:#e3e3e3;--orbit-size:clamp(220px,30vw,420px);--orbit-alpha:.8;--orbit-size-small:calc(var(--orbit-size) * .72);--orbit-out:64px;--orbit-card-half:220px;--orbit-gap:48px;--orbit-haze-clear:50%;--orbit-haze-end:78%;--orbit-haze-alpha:72%;color-scheme:dark}
body.garden{--lt-stage:#f7f0e8;--lt-stage-2:#fbf8f1;--lt-pearl:#403536;--lt-muted:#6f605a;--lt-gold:#98505e;--lt-gold-deep:#98505e;--lt-gold-line:rgba(152,80,94,.38);--lt-gold-glow:rgba(200,110,121,.32);--lt-rose-ink:#98505e;--lt-paper:#fffdf8;--lt-ink:#403536;--lt-glass-strong:rgba(255,253,248,.98);--lt-line:rgba(119,91,82,.18);--lt-primary:#98505e;--lt-primary-ink:#fffdf8;--lt-google-fill:#ffffff;--lt-google-stroke:#747775;--lt-google-font:#1f1f1f;--orbit-alpha:.7;color-scheme:light}
*{box-sizing:border-box}html,body{min-height:100%}body{margin:0;min-height:100dvh;background:var(--lt-stage);color:var(--lt-pearl);font-family:var(--lt-ui);-webkit-font-smoothing:antialiased}a{color:inherit}button,input{font:inherit}button,a,input{-webkit-tap-highlight-color:transparent}:focus-visible{outline:2px solid var(--lt-gold);outline-offset:3px}
.stage{position:relative;display:grid;place-items:center;min-height:100dvh;padding:48px 24px;overflow:hidden;background:radial-gradient(ellipse 82% 68% at 50% 42%,var(--lt-stage-2),var(--lt-stage) 72%),var(--lt-stage)}
.stage::after{content:'';position:absolute;inset:0;background:radial-gradient(ellipse 60% 56% at 50% 46%,transparent 0 var(--orbit-haze-clear),color-mix(in srgb,var(--lt-stage) var(--orbit-haze-alpha),transparent) var(--orbit-haze-end));pointer-events:none}
.orbit{position:absolute;z-index:0;height:var(--orbit-size);width:calc(var(--orbit-size) * .76);object-fit:cover;border:2px solid var(--lt-gold-line);border-radius:16px;box-shadow:0 24px 60px rgba(0,0,0,.46),0 0 22px var(--lt-gold-glow);opacity:var(--orbit-alpha);pointer-events:none}
.o1{left:calc(50% - var(--orbit-card-half) - var(--orbit-gap) - var(--orbit-size) * .76);top:6%;transform:rotate(-8deg)}
.o2{left:calc(50% + var(--orbit-card-half) + var(--orbit-gap));top:6%;transform:rotate(7deg)}
.o3{left:calc(50% - var(--orbit-card-half) - var(--orbit-gap) - var(--orbit-out) - var(--orbit-size-small) * .76);bottom:5%;transform:rotate(-4deg)}
.o4{left:calc(50% + var(--orbit-card-half) + var(--orbit-gap) + var(--orbit-out));bottom:5%;transform:rotate(4deg)}
.o3,.o4{height:var(--orbit-size-small);width:calc(var(--orbit-size-small) * .76)}
body.garden .orbit{box-shadow:0 18px 40px rgba(75,51,42,.16),0 0 18px var(--lt-gold-glow)}
.brand{position:absolute;z-index:3;left:30px;top:26px;display:inline-flex;align-items:baseline;gap:7px;min-height:44px;margin:0;color:var(--lt-pearl);font-size:11px;font-weight:700;letter-spacing:.22em}
.brand small{color:var(--lt-gold);font-size:10px;letter-spacing:.12em}
body.garden .brand{color:var(--lt-ink);font-family:var(--lt-reading);font-size:17px;letter-spacing:.04em}
body.garden .brand small{color:var(--lt-gold);font-family:var(--lt-ui);letter-spacing:.12em}
.auth-card{position:relative;z-index:2;width:min(440px,100%);padding:36px;border:1px solid var(--lt-gold-line);border-radius:var(--lt-r-panel);background:var(--lt-glass-strong);color:var(--lt-pearl);box-shadow:0 32px 96px rgba(0,0,0,.58),0 0 0 1px var(--lt-gold-line),0 0 34px var(--lt-gold-glow);backdrop-filter:blur(18px)}
body.garden .auth-card{background:var(--lt-paper);color:var(--lt-ink);border-color:var(--lt-gold-line);box-shadow:var(--lt-garden-shadow),0 0 0 1px var(--lt-gold-line)}
.eyebrow{margin:0 0 8px;color:var(--lt-muted);font-size:10px;font-weight:700;letter-spacing:.2em}
body.garden .eyebrow{color:var(--lt-rose-ink)}
h1{margin:0 0 24px;font-size:clamp(28px,4vw,34px);line-height:1.25;letter-spacing:-.04em;font-weight:600}
body.garden h1{font-family:var(--lt-reading);font-size:clamp(30px,4.2vw,36px);font-weight:700;letter-spacing:.01em}
.btn{display:flex;align-items:center;justify-content:center;gap:9px;width:100%;min-height:48px;padding:0 18px;border:1px solid transparent;border-radius:var(--lt-r-pill);font-size:15px;font-weight:600;line-height:1.2;text-align:center;text-decoration:none;cursor:pointer}
.btn.primary{background:var(--lt-primary);color:var(--lt-primary-ink)}
.btn.primary:hover{filter:brightness(1.03)}
.btn.google{background:var(--lt-google-fill);color:var(--lt-google-font);border:1px solid var(--lt-google-stroke);font-family:'Roboto',var(--lt-ui);font-weight:500;font-size:14px;line-height:20px}
.btn.google:hover{filter:brightness(1.06)}
.btn.google .g-logo{display:block;flex:0 0 auto;width:18px;height:18px}
.divider{display:flex;align-items:center;gap:12px;margin:20px 0 4px;color:var(--lt-muted);font-size:11px;letter-spacing:.04em}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:var(--lt-line)}
.field{display:grid;gap:7px;margin-top:14px;color:var(--lt-pearl);font-size:12px;font-weight:600}
body.garden .field{color:var(--lt-ink)}
.field small{color:var(--lt-muted);font-size:11px;font-weight:400}
.field input{width:100%;height:48px;padding:0 14px;border:1px solid var(--lt-line);border-radius:12px;background:rgba(255,255,255,.04);color:var(--lt-pearl);font-size:15px;font-weight:400}
.field input::placeholder{color:var(--lt-muted);opacity:.8}
.field input:focus{outline:none;border-color:var(--lt-gold);box-shadow:0 0 0 3px var(--lt-gold-line)}
body.garden .field input{background:var(--lt-paper);color:var(--lt-ink);border-color:var(--lt-line)}
body.garden .field input:focus{box-shadow:0 0 0 3px var(--lt-gold-line)}
.error{min-height:18px;margin:12px 0 0;color:var(--lt-pearl);font-size:12px;line-height:1.5}
body.garden .error{color:var(--lt-rose-ink)}
.submit{margin-top:14px}
.alt-link{display:flex;align-items:center;justify-content:center;min-height:44px;margin-top:12px;color:var(--lt-pearl);font-size:13px;text-decoration:underline;text-underline-offset:4px}
body.garden .alt-link{color:var(--lt-ink)}
.foot{position:absolute;z-index:2;bottom:18px;left:50%;transform:translateX(-50%);margin:0;color:var(--lt-muted);font-size:11px;letter-spacing:.04em;white-space:nowrap}
@media (max-width:680px){.stage{padding:72px 16px 30px;place-items:start center}.stage::after{background:radial-gradient(ellipse 56% 52% at 50% 46%,transparent 0 42%,var(--lt-stage) 82%)}.brand{left:18px;top:16px}.orbit{width:128px;height:168px;opacity:.34}.o1{left:-26px;top:6%}.o2{left:auto;right:-28px;top:9%}.o3{left:auto;right:8%;bottom:2%;width:104px;height:137px}.o4{display:none}.auth-card{width:100%;padding:25px 22px;border-radius:18px}.auth-card h1{margin-bottom:18px}.foot{position:static;transform:none;margin-top:20px;text-align:center;white-space:normal}.divider{margin-top:16px}}
`;

export const AUTH_SKIN_CARD_IMAGES = Object.freeze([
  ['o1', '/assets/auth-skin/card-1.webp'],
  ['o2', '/assets/auth-skin/card-3.webp'],
  ['o3', '/assets/auth-skin/card-4.webp'],
  ['o4', '/assets/auth-skin/card-2.webp'],
]);

const shell = ({ brand, headingId, title, lang, theme, body, head = '' }) => `<!doctype html><html lang="${esc(lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title><meta name="referrer" content="no-referrer"><style>${AUTH_SKIN_CSS}</style>${head}</head><body class="${esc(theme)}"><div class="stage">${AUTH_SKIN_CARD_IMAGES.map(([cls, src]) => `<img class="orbit ${cls}" src="${esc(src)}" alt="" width="240" height="316">`).join('')}<p class="brand"><span>${esc(brand.wordmark)}</span><small>${esc(brand.wordmarkSuffix)}</small></p><main class="auth-card" aria-labelledby="${esc(headingId)}">${body}</main><p class="foot">${esc(padiemAccountLine(lang))}</p></div></body></html>`;

const hiddenTheme = (theme) => `<input type="hidden" name="lt_theme" value="${esc(theme)}">`;

const emailField = (s) => `<label class="field" for="email">${esc(s.email)}<input id="email" name="email" type="email" required maxlength="255" autocomplete="username"></label>`;
const passwordField = (s, autocomplete) => `<label class="field" for="password">${esc(s.password)}<input id="password" name="password" type="password" required maxlength="128" autocomplete="${esc(autocomplete)}"></label>`;

export function brandLoginPage({ brand, theme, lang, googleHref, formAction, signupHref, message = '', showGoogle = true }) {
  const s = brand.strings[lang] || brand.strings.ko;
  const google = showGoogle && googleHref
    ? `<a class="btn google" href="${esc(googleHref)}"><img class="g-logo" src="/assets/auth-skin/googleg-standard-color.svg" alt="" width="18" height="18">${esc(s.google)}</a><div class="divider"><span>${esc(s.divider)}</span></div>`
    : '';
  const body = `<p class="eyebrow">${esc(s.eyebrow)}</p><h1 id="login-title">${esc(s.loginTitle)}</h1>${google}<form method="post" action="${esc(formAction)}">${hiddenTheme(theme)}${emailField(s)}${passwordField(s, 'current-password')}<p class="error" role="alert">${esc(message)}</p><button class="btn primary submit" type="submit">${esc(s.loginSubmit)}</button></form><a class="alt-link" href="${esc(signupHref)}">${esc(s.loginAlt)}</a>`;
  return shell({ brand, headingId: 'login-title', title: `${s.loginTitle} · ${brand.wordmark}`, lang, theme, body });
}

export function brandSignupPage({ brand, theme, lang, formAction, loginHref, message = '' }) {
  const s = brand.strings[lang] || brand.strings.ko;
  const body = `<p class="eyebrow">${esc(s.eyebrow)}</p><h1 id="signup-title">${esc(s.signupTitle)}</h1><form method="post" action="${esc(formAction)}">${hiddenTheme(theme)}<label class="field" for="name">${esc(s.name)} <small>${esc(s.optional)}</small><input id="name" name="name" type="text" maxlength="160" autocomplete="name"></label>${emailField(s)}${passwordField(s, 'new-password')}<p class="error" role="alert">${esc(message)}</p><button class="btn primary submit" type="submit">${esc(s.signupSubmit)}</button></form><a class="alt-link" href="${esc(loginHref)}">${esc(s.signupAlt)}</a>`;
  return shell({ brand, headingId: 'signup-title', title: `${s.signupTitle} · ${brand.wordmark}`, lang, theme, body });
}

// Rules for the signup confirmation screen only (#7679). They travel in that
// page's own style element so the login and signup screens keep their bytes.
export const AUTH_SKIN_COMPLETE_CSS = '.auth-card h1{margin-bottom:12px}.done-lead{margin:0 0 6px;color:var(--lt-muted);font-size:14px;line-height:1.6}.done-email{margin:0 0 24px;font-size:17px;font-weight:600;line-height:1.4;overflow-wrap:anywhere}.done-note{margin:14px 0 0;color:var(--lt-muted);font-size:12px;line-height:1.5;text-align:center}';

export function brandSignupCompletePage({ brand, theme, lang, email, continueHref }) {
  const s = brand.strings[lang] || brand.strings.ko;
  const text = signupCompleteText(lang);
  const body = `<p class="eyebrow">${esc(s.eyebrow)}</p>${signupCompleteBody({ text, action: s.completeAction, email, href: continueHref, buttonClass: 'btn primary', headingId: 'signup-complete-title' })}`;
  return shell({ brand, headingId: 'signup-complete-title', title: `${text.title} · ${brand.wordmark}`, lang, theme, body, head: `${signupCompleteRefresh(continueHref)}<style>${AUTH_SKIN_COMPLETE_CSS}</style>` });
}
