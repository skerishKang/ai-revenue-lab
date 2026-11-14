// One confirmation screen after an email signup (#7679).
//
// The signup is already finished when this renders: the account, the one-time
// code and the cleared login cookie are exactly what the immediate redirect
// carried before. The screen only tells the person which address they signed
// up with, then returns them to the service on its own or by the button.
export const SIGNUP_COMPLETE_DELAY_SECONDS = 5;

const TEXT = Object.freeze({
  ko: Object.freeze({
    title: '가입했어요',
    lead: '이 이메일로 로그인하시면 됩니다.',
    action: '서비스로 돌아가기',
    auto: `${SIGNUP_COMPLETE_DELAY_SECONDS}초 뒤 자동으로 이동합니다.`,
  }),
  en: Object.freeze({
    title: 'You are signed up',
    lead: 'Use this email to sign in from now on.',
    action: 'Return to the service',
    auto: `You will be taken back in ${SIGNUP_COMPLETE_DELAY_SECONDS} seconds.`,
  }),
});

export function signupCompleteText(lang) {
  return TEXT[lang === 'en' ? 'en' : 'ko'];
}

// Enough of the address to recognise it, not enough to read it off a screen.
export function maskEmail(email) {
  const value = String(email ?? '');
  const at = value.lastIndexOf('@');
  if (at < 1) return '***';
  const local = [...value.slice(0, at)];
  return `${local.slice(0, local.length > 2 ? 2 : 1).join('')}***${value.slice(at)}`;
}

const esc = (value) => String(value)
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

// The return address is a registered redirect URI plus the code and state the
// redirect would have carried; it is only ever written as an escaped attribute.
export const signupCompleteRefresh = (href) =>
  `<meta http-equiv="refresh" content="${SIGNUP_COMPLETE_DELAY_SECONDS};url=${esc(href)}">`;

export const signupCompleteBody = ({ text, action, email, href, buttonClass, headingId = '' }) =>
  `<h1${headingId ? ` id="${esc(headingId)}"` : ''}>${esc(text.title)}</h1><p class="done-lead">${esc(text.lead)}</p><p class="done-email">${esc(maskEmail(email))}</p><a class="${esc(buttonClass)}" href="${esc(href)}">${esc(action)}</a><p class="done-note">${esc(text.auto)}</p>`;

// Only this screen carries these rules, so every other plain screen keeps its
// bytes.
export const PLAIN_SIGNUP_COMPLETE_CSS = 'h1{margin-bottom:12px}.done-lead{margin:0 0 6px;text-align:center;font-size:14px;color:#5f6368}.done-email{margin:0 0 20px;text-align:center;font-size:16px;font-weight:600;overflow-wrap:anywhere}.done-note{margin:12px 0 0;text-align:center;font-size:12px;color:#5f6368}';
