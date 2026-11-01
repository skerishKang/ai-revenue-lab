import assert from 'node:assert/strict';
import {createHash,createHmac} from 'node:crypto';
import {bookaiSignedHeaders} from '../public/bookai-com2-signature.mjs';
const secret='synthetic-test-key', timestamp=1761960000, subject='sub_test123';
for (const [method,path,body] of [
  ['GET','/api/bookai/records?since=123&limit=500',''],
  ['POST','/api/bookai/records','{"records":[{"record_id":"test"}]}']
]) {
  const digest=createHash('sha256').update(body,'utf8').digest('hex');
  const expected=createHmac('sha256',secret).update([method,path,timestamp,subject,digest].join('\n')).digest('hex');
  const h=await bookaiSignedHeaders({method,path,timestamp,subject,body,secret});
  assert.equal(h['X-Bookai-Signature'],expected);
  assert.equal(h['X-Bookai-Subject'],subject);
  assert.equal(h['X-Bookai-Timestamp'],String(timestamp));
}
await assert.rejects(bookaiSignedHeaders({method:'GET',path:'/api/bookai/records',timestamp,subject,body:'x',secret}));
await assert.rejects(bookaiSignedHeaders({method:'GET',path:'/other',timestamp,subject,secret}));
console.log('PASS: GET and POST v1 signatures match independent Node HMAC; invalid requests rejected');
