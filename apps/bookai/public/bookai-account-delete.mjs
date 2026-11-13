import {com2SignedHeaders} from './com2-hmac.mjs';

export const ACCOUNT_DELETE_PATH = '/api/bookai/account/shared-delete';
const ORIGIN = 'https://bookai.padiem.net';
const headers = {'cache-control':'no-store','referrer-policy':'no-referrer'};
const reply = (body, status=200) => Response.json(body, {status,headers});

export async function accountDeleteSignedHeaders(options) {
  if (options.method !== 'POST' || options.path !== ACCOUNT_DELETE_PATH)
    throw Error('invalid_request');
  return com2SignedHeaders(options);
}

async function confirmation(request) {
  if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') return false;
  const reader = request.body?.getReader();
  if (!reader) return false;
  const chunks = []; let size = 0;
  for (;;) {
    const {done,value} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 1024) { await reader.cancel(); return false; }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.byteLength; }
  try {
    const data = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    return data && !Array.isArray(data) && Object.keys(data).length === 2 && data.confirm === true &&
      /^sub_[A-Za-z0-9_-]+$/.test(data.account_id || '') ? data.account_id : false;
  } catch { return false; }
}

// Reuse the existing refresh grant to check revocation and account state before
// signing a deletion request. Neither credential leaves this Worker boundary.
export async function deleteBookAIAccount(request, env, ports) {
  const {identity,cookies,exchange,verify,sessionCookies,clearCookies,withCookies,fetcher,clock} = ports;
  if (request.method !== 'POST') return reply({error:'method_not_allowed'},405);
  if (request.headers.get('origin') !== ORIGIN) return reply({error:'invalid_origin'},403);
  const confirmedAccount = await confirmation(request);
  if (new URL(request.url).search || !confirmedAccount) return reply({error:'invalid_request'},400);
  let rotated = [];
  try {
    const current = await identity(request), refresh = cookies(request).__Host_bookai_refresh;
    if (!refresh) return reply({error:'not_authenticated'},401);
    if (current && current.accountId !== confirmedAccount) return reply({error:'not_authenticated'},401);
    if (!env.BOOKAI_COM2_SYNC_SECRET) return reply({error:'account_delete_unavailable'},503);
    const tokens = await exchange(env,{grant_type:'refresh_token',refresh_token:refresh});
    const verified = await verify(tokens.access_token);
    if (verified.accountId !== confirmedAccount || current &&
        (verified.accountId !== current.accountId || verified.sessionId !== current.sessionId))
      return reply({error:'not_authenticated'},401);
    rotated = sessionCookies(tokens);
    const body = JSON.stringify({confirm:true,session_id:verified.sessionId,
      expires_at:verified.expiresAt,request_id:crypto.randomUUID()});
    const signed = await accountDeleteSignedHeaders({method:'POST',path:ACCOUNT_DELETE_PATH,
      timestamp:Math.floor(clock()/1000),subject:verified.accountId,body,secret:env.BOOKAI_COM2_SYNC_SECRET});
    const upstream = await fetcher('https://chat.padiem.net'+ACCOUNT_DELETE_PATH,
      {method:'POST',headers:{...signed,'content-type':'application/json'},body,redirect:'manual'});
    if (!upstream.ok) {
      const status = [401,403].includes(upstream.status) ? upstream.status : 503;
      let error = status === 503 ? 'account_delete_unavailable' : 'not_authenticated';
      if (status === 403) {
        try { if ((await upstream.json()).error === 'account_delete_admin_blocked') error = 'account_delete_admin_blocked'; }
        catch { /* Keep the fixed authentication error for unrecognized bodies. */ }
      }
      return withCookies(reply({error},status),rotated);
    }
    const result = await upstream.json();
    if (result?.ok !== true || result.common_account_deleted !== true ||
        typeof result.cleanup?.complete !== 'boolean' ||
        !Number.isSafeInteger(result.cleanup.pending) || result.cleanup.pending < 0 ||
        result.cleanup.complete !== (result.cleanup.pending === 0)) throw Error('invalid_response');
    return withCookies(reply({ok:true,common_account_deleted:true,
      cleanup:{complete:result.cleanup.complete,pending:result.cleanup.pending}}),clearCookies());
  } catch (error) {
    const status = [400,401,403].includes(error?.status) ? 401 : 503;
    return withCookies(reply({error:status === 401 ? 'not_authenticated' : 'account_delete_unavailable'},status),rotated);
  }
}
