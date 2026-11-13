// Mailbox recovery UI and bounded input helpers. No token appears in server HTML.
const strings = {
  ko: {
    title: '이메일 계정 복구', email: '이메일', request: '복구 링크 요청',
    requested: '복구할 수 있는 경우 이메일로 안내를 보내드립니다. 메일을 확인해 주세요.',
    password: '새 비밀번호', submit: '새 비밀번호 저장',
    complete: '비밀번호를 저장했습니다. 이용하던 서비스에서 다시 로그인해 주세요.',
    invalid: '복구 링크가 올바르지 않거나 더 이상 유효하지 않습니다. 새 링크를 요청해 주세요.',
    passwordInvalid: '새 비밀번호 형식을 확인해 주세요. 8~128자이며 이메일이나 이메일 아이디를 포함할 수 없습니다.',
    unavailable: '지금은 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.',
    refused: '가입을 완료할 수 없습니다. 로그인하거나 이메일 계정 복구를 이용해 주세요.',
  },
  en: {
    title: 'Recover your email account', email: 'Email', request: 'Request a recovery link',
    requested: 'If recovery is available, we will send instructions by email. Please check your inbox.',
    password: 'New password', submit: 'Save new password',
    complete: 'Your password has been saved. Sign in again from the service you were using.',
    invalid: 'This recovery link is invalid or no longer available. Please request a new link.',
    passwordInvalid: 'Check your new password. Use 8–128 characters without your email or email username.',
    unavailable: 'This request cannot be completed right now. Please try again shortly.',
    refused: 'Sign-up could not be completed. Please sign in or use email account recovery.',
  },
};
// #7679 password find: the same pages and the same mailed proof, worded for
// the person who forgot a password. Shown only while its own switch is on.
const findStrings = {
  ko: {
    ...strings.ko,
    title: '비밀번호 찾기', entry: '비밀번호 찾기', request: '링크 받기',
    intro: '가입한 이메일을 입력하면 비밀번호를 새로 정할 수 있는 링크를 보내드립니다.',
    google: 'Google로 가입한 계정은 비밀번호가 없습니다. 로그인 화면에서 Google로 계속해 주세요.',
    requested: '이 이메일로 가입한 계정이 있으면 비밀번호를 새로 정할 수 있는 링크를 보내드립니다. 링크는 15분 동안 한 번만 쓸 수 있습니다. 메일이 오지 않으면 주소를 확인하고 잠시 뒤 다시 요청해 주세요.',
    complete: '비밀번호를 바꿨습니다. 이용하던 서비스에서 새 비밀번호로 로그인해 주세요. 다른 기기에서도 다시 로그인해야 합니다.',
    invalid: '링크가 올바르지 않거나 더 이상 쓸 수 없습니다. 비밀번호 찾기를 다시 요청해 주세요.',
    refused: '가입을 완료할 수 없습니다. 로그인하거나 비밀번호 찾기를 이용해 주세요.',
  },
  en: {
    ...strings.en,
    title: 'Reset your password', entry: 'Forgot your password?', request: 'Send the link',
    intro: 'Enter the email you signed up with and we will send a link to set a new password.',
    google: 'An account created with Google has no password. Use Continue with Google on the sign-in screen.',
    requested: 'If an account uses this email, we will send a link to set a new password. The link works once, for 15 minutes. If nothing arrives, check the address and try again shortly.',
    complete: 'Your password has been changed. Sign in with the new password from the service you were using. Other devices will need to sign in again.',
    invalid: 'This link is invalid or can no longer be used. Please request a new one.',
    refused: 'Sign-up could not be completed. Please sign in or use Forgot your password.',
  },
};
export const recoveryStrings = (lang, find = false) => (find ? findStrings : strings)[lang === 'en' ? 'en' : 'ko'];
export const emailRecoveryEnabled = value => value === true || String(value ?? '').trim().toLowerCase() === 'true';
export const validRecoveryToken = token => typeof token === 'string' && /^[A-Za-z0-9_-]{43}$/.test(token);
export const validRecoveryEmail = value => typeof value === 'string' && value.length <= 255 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');

export function addRecoveryLink(html, lang, find = false) {
  const text = recoveryStrings(lang, find);
  return html.replace('</main>', `<a class="link alt-link" href="/password/recovery">${esc(find ? text.entry : text.title)}</a></main>`);
}

export function recoveryPage(kind, lang, find = false) {
  const text = recoveryStrings(lang, find);
  // The same two lines for every visitor: nothing here depends on an account.
  const guide = find && kind === 'request' ? `<p>${esc(text.intro)}</p>` : '';
  const hint = find && kind !== 'confirm' ? `<p class="hint">${esc(text.google)}</p>` : '';
  const form = kind === 'request'
    ? `${guide}<form method="post" action="/password/recovery/request"><label for="email">${esc(text.email)}</label><input id="email" name="email" type="email" required maxlength="255" autocomplete="email"><button type="submit">${esc(text.request)}</button></form>${hint}`
    : kind === 'confirm'
      ? `<form id="recovery" method="post" action="/password/recovery/confirm"><label for="new-password">${esc(text.password)}</label><input id="new-password" name="new_password" type="password" required minlength="8" maxlength="128" autocomplete="new-password"><button type="submit">${esc(text.submit)}</button></form><p id="result" role="status"></p><script>${recoveryClient(text)}</script>`
      : `<p role="status">${esc(text.requested)}</p>${hint}`;
  return `<!doctype html><html lang="${lang === 'en' ? 'en' : 'ko'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>${esc(text.title)}</title><style>body{font-family:system-ui,sans-serif;background:#f5f6f8;margin:0;padding:24px;color:#1c1e21}main{max-width:360px;margin:10vh auto;padding:28px;background:white;border-radius:12px}h1{font-size:22px}label,input,button{display:block;width:100%;box-sizing:border-box}input,button{padding:12px;margin:10px 0 18px;border:1px solid #dadce0;border-radius:8px}button{background:#1a73e8;color:white;cursor:pointer}p{line-height:1.6}${find ? '.hint{font-size:13px;color:#5f6368}' : ''}</style></head><body><main><h1>${esc(text.title)}</h1>${form}</main></body></html>`;
}

function recoveryClient(text) {
  // A URL fragment is never sent in the initial HTTP request or Referer. Clear
  // it before any network activity; only the confirming POST sends the proof.
  return `(()=>{const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'',location.pathname);const form=document.getElementById('recovery'),result=document.getElementById('result');form.addEventListener('submit',async event=>{event.preventDefault();const button=form.querySelector('button');button.disabled=true;try{const response=await fetch('/password/recovery/confirm',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({token,new_password:form.elements.new_password.value})});const data=await response.json();result.textContent=data.message||${JSON.stringify(text.unavailable)};if(data.ok){form.reset();form.hidden=true;}}catch{result.textContent=${JSON.stringify(text.unavailable)};}finally{button.disabled=false;}});})();`;
}

export async function recoveryBody(request) {
  if (Number(request.headers.get('content-length') || 0) > 4096) throw new Error('recovery_body_too_large');
  const reader = request.body?.getReader();
  if (!reader) return '';
  const chunks = []; let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 4096) { await reader.cancel(); throw new Error('recovery_body_too_large'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
}
