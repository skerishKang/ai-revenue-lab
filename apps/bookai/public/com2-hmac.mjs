// Shared COM2 HMAC canonicalization. Deploy-local copies must stay byte-identical.
const enc = new TextEncoder();
const hex = bytes => Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, '0')).join('');
export async function com2SignedHeaders({method, path, timestamp, subject, body = '', secret}) {
  if (!['GET','POST'].includes(method) || typeof path !== 'string' || !path.startsWith('/') ||
      path.startsWith('//') || /[\r\n#]/.test(path)) throw new Error('invalid_request');
  if (!/^sub_[A-Za-z0-9_-]+$/.test(subject) || !/^\d+$/.test(String(timestamp))) throw new Error('invalid_identity');
  if (typeof secret !== 'string' || !secret || typeof body !== 'string' || (method === 'GET' && body)) throw new Error('invalid_request');
  const digest = hex(await crypto.subtle.digest('SHA-256', enc.encode(body)));
  const canonical = [method,path,String(timestamp),subject,digest].join('\n');
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), {name:'HMAC',hash:'SHA-256'}, false, ['sign']);
  const signature = hex(await crypto.subtle.sign('HMAC', key, enc.encode(canonical)));
  return {'X-Bookai-Subject':subject,'X-Bookai-Timestamp':String(timestamp),'X-Bookai-Signature':signature};
}
