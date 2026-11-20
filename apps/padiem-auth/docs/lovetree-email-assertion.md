# 러브트리 email_assertion 검증 (#8175)

padiem-auth는 `client_id=lovetree-4-0`의 코드→토큰 교환 응답 본문에만 `email_assertion`을 실어 준다.
브라우저 주소·로그·오류 메시지에는 이메일이 실리지 않는다. 새 Worker 비밀
`PADIEM_AUTH_EMAIL_ASSERTION_KEY_LOVETREE`가 설정되지 않았으면 필드 자체가 없다.
배포 시 같은 값을 padiem-auth와 러브트리 서버 환경에 넣는다(값은 저장소에 쓰지 않는다).

## 형식

```
email_assertion = "v1." + base64url(JSON) + "." + base64url(HMAC-SHA256(key, "v1." + payload))
payload = { sub, email(소문자), email_verified, aud: "lovetree", iat(초), exp: iat + 600 }
```

## 검증 예시 (JS, 러브트리 서버)

```js
const encoder = new TextEncoder();
const unb64url = (s) => Uint8Array.from(
  atob(s.replaceAll('-', '+').replaceAll('_', '/').padEnd(Math.ceil(s.length / 4) * 4, '=')),
  (c) => c.charCodeAt(0));

export async function verifyEmailAssertion(assertion, secret, now = Math.floor(Date.now() / 1000)) {
  const parts = (assertion || '').split('.');
  if (parts.length !== 3 || parts[0] !== 'v1') return null;
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const expected = new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode('v1.' + parts[1])));
  const given = unb64url(parts[2]);
  if (given.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < given.length; i += 1) diff |= given[i] ^ expected[i];
  if (diff !== 0) return null;
  const claim = JSON.parse(new TextDecoder().decode(unb64url(parts[1])));
  if (claim.aud !== 'lovetree' || claim.exp !== claim.iat + 600 ||
      now < claim.iat || now >= claim.exp) return null;
  if (typeof claim.sub !== 'string' || !claim.sub ||
      typeof claim.email !== 'string' || !claim.email ||
      typeof claim.email_verified !== 'boolean') return null;
  return claim;
}
```

서명이 맞고 `aud`·만료가 통과한 경우에만 `claim.email`을 저장한다. 이메일은 대소문자를 가리지 않으므로 저장 전 소문자로 정규화한다.

## 시험 벡터 (가짜 비밀)

이 값은 문서용 예제이며 실제 배포 비밀이 아니다.

- key: `doc-vector-fake-secret`
- now: `1760000000`
- assertion:

```
v1.eyJzdWIiOiJzdWJfZG9jX3ZlY3RvciIsImVtYWlsIjoib3duZXJAZXhhbXBsZS50ZXN0IiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImF1ZCI6ImxvdmV0cmVlIiwiaWF0IjoxNzYwMDAwMDAwLCJleHAiOjE3NjAwMDA2MDB9.Fi7D0cVLibuEzWaK2jAiidMgcZm0cSEsyK1StFM3gf0
```

기대 payload:

```json
{"sub":"sub_doc_vector","email":"owner@example.test","email_verified":true,"aud":"lovetree","iat":1760000000,"exp":1760000600}
```

## 환경 변수 이름 (값 없음)

`PADIEM_AUTH_EMAIL_ASSERTION_KEY_LOVETREE` — `wrangler secret put`으로만 설정한다.
