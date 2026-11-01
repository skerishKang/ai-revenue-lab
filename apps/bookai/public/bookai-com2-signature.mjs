// BookAI / COM2 records protocol v1. No credentials are stored in this module.
const enc = new TextEncoder();
const hex = bytes => Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, '0')).join('');
const validPath = path => path === '/api/bookai/records' || path.startsWith('/api/bookai/records?');
export async function bookaiSignedHeaders({method, path, timestamp, subject, body = '', secret}) {
  if (!['GET','POST'].includes(method) || !validPath(path) || /[\r\n#]/.test(path)) throw new Error('invalid_request');
  if (!/^sub_[A-Za-z0-9_-]+$/.test(subject) || !/^\d+$/.test(String(timestamp))) throw new Error('invalid_identity');
  if (typeof secret !== 'string' || !secret || typeof body !== 'string' || (method === 'GET' && body)) throw new Error('invalid_request');
  const digest = hex(await crypto.subtle.digest('SHA-256', enc.encode(body)));
  const canonical = [method,path,String(timestamp),subject,digest].join('\n');
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), {name:'HMAC',hash:'SHA-256'}, false, ['sign']);
  const signature = hex(await crypto.subtle.sign('HMAC', key, enc.encode(canonical)));
  return {'X-Bookai-Subject':subject,'X-Bookai-Timestamp':String(timestamp),'X-Bookai-Signature':signature};
}
