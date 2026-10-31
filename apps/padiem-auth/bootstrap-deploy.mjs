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

export async function runBootstrap({ executable = 'node_modules/.bin/wrangler', launch = spawn } = {}) {
  const { kid, jwks, secrets } = makeBootstrap();
  const args = ['deploy', '--config', 'apps/padiem-auth/wrangler.toml', '--secrets-file', '/dev/stdin', '--var', `PADIEM_AUTH_SIGNING_KID:${kid}`, '--var', `PADIEM_AUTH_JWKS:${JSON.stringify(jwks)}`];
  // A shell pipe creates a real pipe for /dev/stdin; Node's direct child pipe
  // is a socket on Linux and cannot be reopened via /dev/stdin. Arguments are
  // forwarded as positional parameters, never interpolated into shell code.
  const child = launch('bash', ['-c', 'set -o pipefail; cat | "$@"', 'padiem-auth-bootstrap', executable, ...args], { stdio: ['pipe', 'ignore', 'ignore'] });
  child.stdin.end(JSON.stringify(secrets));
  return await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', code => code === 0 ? resolve() : reject(new Error(`initial worker deployment failed (exit ${code})`)));
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await runBootstrap();
}
