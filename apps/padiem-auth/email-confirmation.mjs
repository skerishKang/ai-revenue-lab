// Optional "is this address yours" mail after an email signup (#7679).
//
// The signup is complete without it and the account works whether or not the
// link is ever opened. Opening it and pressing the button marks the address as
// confirmed, and from the next sign-in the profile handed to a service says so.
// Chat sends the mail and keeps nothing; this Worker keeps only a digest of the
// link, and the page never contains the token.
export const EMAIL_CONFIRMATION_TTL_SECONDS = 7 * 24 * 3600;
const DIGEST_DOMAIN = 'padiem-email-confirmation:v1\0';

const strings = {
  ko: {
    title: '이메일 확인',
    lead: '이 이메일로 PADIEM 계정에 가입하신 분이 맞으면 아래 버튼을 눌러 주세요. 누르지 않아도 계정은 그대로 쓸 수 있습니다.',
    submit: '맞아요, 제 이메일입니다',
    complete: '이메일을 확인했습니다. 이 창은 닫으셔도 됩니다.',
    invalid: '링크가 올바르지 않거나 더 이상 쓸 수 없습니다. 확인하지 않아도 계정은 그대로 쓸 수 있습니다.',
    unavailable: '지금은 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  },
  en: {
    title: 'Confirm your email',
    lead: 'If you signed up for a PADIEM account with this email, press the button below. Your account keeps working even if you do not.',
    submit: 'Yes, this is my email',
    complete: 'Your email is confirmed. You can close this window.',
    invalid: 'This link is invalid or can no longer be used. Your account keeps working without it.',
    unavailable: 'This request cannot be completed right now. Please try again shortly.',
  },
};
export const confirmationStrings = lang => strings[lang === 'en' ? 'en' : 'ko'];
export const validConfirmationToken = token => typeof token === 'string' && /^[A-Za-z0-9_-]{43}$/.test(token);
export const validConfirmationDigest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

// The same digest Chat reports for the link it mailed. Only this is stored.
export async function confirmationTokenDigest(token) {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(DIGEST_DOMAIN + token)));
  return [...bytes].map(x => x.toString(16).padStart(2, '0')).join('');
}

const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');

export function confirmationPage(lang) {
  const text = confirmationStrings(lang);
  // The button is deliberate: opening the link alone confirms nothing, so a
  // mail scanner that follows links cannot confirm an address.
  return `<!doctype html><html lang="${lang === 'en' ? 'en' : 'ko'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>${esc(text.title)}</title><style>body{font-family:system-ui,sans-serif;background:#f5f6f8;margin:0;padding:24px;color:#1c1e21}main{max-width:360px;margin:10vh auto;padding:28px;background:white;border-radius:12px}h1{font-size:22px}button{display:block;width:100%;box-sizing:border-box;padding:12px;margin:10px 0 18px;border:1px solid #1a73e8;border-radius:8px;background:#1a73e8;color:white;cursor:pointer}p{line-height:1.6;word-break:keep-all}</style></head><body><main><h1>${esc(text.title)}</h1><form id="confirm" method="post" action="/email/confirm"><p>${esc(text.lead)}</p><button type="submit">${esc(text.submit)}</button></form><p id="result" role="status"></p><script>${confirmationClient(text)}</script></main></body></html>`;
}

function confirmationClient(text) {
  // A URL fragment is never sent in the page request or in a Referer. It is
  // cleared before anything else; only the confirming POST carries the token.
  return `(()=>{const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'',location.pathname);const form=document.getElementById('confirm'),result=document.getElementById('result');form.addEventListener('submit',async event=>{event.preventDefault();const button=form.querySelector('button');button.disabled=true;try{const response=await fetch('/email/confirm',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({token})});const data=await response.json();result.textContent=data.message||${JSON.stringify(text.unavailable)};if(data.ok||response.status===400){form.hidden=true;}}catch{result.textContent=${JSON.stringify(text.unavailable)};}finally{button.disabled=false;}});})();`;
}
