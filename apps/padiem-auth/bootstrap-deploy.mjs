import { generateKeyPairSync, randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';

// Secrets are generated only inside the deployment process, then delivered to
// Wrangler over stdin. The public JWK is published as a normal Worker var.
export function makeBootstrap() {
  const pair = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  const kid = 'auth-' + randomBytes(12).toString('hex');
  const publicKey = { ...pair.publicKey.export({ format: 'jwk' }), kid, alg: 'ES256', use: 'sig' };
  const secrets = {
    PADIEM_AUTH_ES256_PRIVATE_JWK: JSON.stringify(pair.privateKey.export({ format: 'jwk' })),
    PADIEM_AUTH_IDENTITY_HMAC_KEY: randomBytes(32).toString('base64url'),
    PADIEM_AUTH_REFRESH_ENCRYPTION_KEY: randomBytes(32).toString('base64url')
  };
  return { kid, jwks: { keys: [publicKey] }, secrets };
}

export function redactDiagnostics(output, secrets, extra = []) {
  const privateJwk = JSON.parse(secrets.PADIEM_AUTH_ES256_PRIVATE_JWK);
  const sensitive = [...Object.values(secrets), privateJwk.d, ...extra].filter(x => typeof x === 'string' && x.length > 0);
  const forms = sensitive.flatMap(value => [value, JSON.stringify(value).slice(1, -1), encodeURIComponent(value)]).sort((a, b) => b.length - a.length);
  let text = output;
  for (const value of forms) text = text.split(value).join('[REDACTED]');
  return text;
}

export async function runBootstrap({ executable = 'node_modules/.bin/wrangler', launch = spawn, emitError = text => process.stderr.write(text) } = {}) {
  const { kid, jwks, secrets } = makeBootstrap();
  const args = ['deploy', '--config', 'apps/padiem-auth/wrangler.toml', '--secrets-file', '/dev/stdin', '--var', `PADIEM_AUTH_SIGNING_KID:${kid}`, '--var', `PADIEM_AUTH_JWKS:${JSON.stringify(jwks)}`];
  // A shell pipe creates a real pipe for /dev/stdin; Node's direct child pipe
  // is a socket on Linux and cannot be reopened via /dev/stdin. Arguments are
  // forwarded as positional parameters, never interpolated into shell code.
  const child = launch('bash', ['-c', 'set -o pipefail; cat | "$@"', 'padiem-auth-bootstrap', executable, ...args], { stdio: ['pipe', 'ignore', 'pipe'] });
  // Buffer before masking so a secret split across output chunks cannot escape.
  const errors = [];
  child.stderr.on('data', chunk => errors.push(Buffer.from(chunk)));
  child.stdin.end(JSON.stringify(secrets));
  return await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', code => {
      const output = redactDiagnostics(Buffer.concat(errors).toString('utf8'), secrets, [process.env.CLOUDFLARE_API_TOKEN, process.env.CLOUDFLARE_ACCOUNT_ID]);
      if (output) emitError(output);
      code === 0 ? resolve() : reject(new Error(`initial worker deployment failed (exit ${code})`));
    });
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await runBootstrap();
}
