#!/usr/bin/env node
// Operator reset of today's failed-login count for one address (owner
// decision 2026-11-24). The #7789 limit (50 refused passwords per address per
// UTC day) is unchanged; this only clears one address before the day ends.
//
// Usage:
//   PADIEM_AUTH_ADMIN_SECRET_FILE=<path to a file holding the secret> \
//     node tools/reset-login-budget.mjs <address> [--origin https://auth.padiem.net]
//   (PADIEM_AUTH_ADMIN_SECRET works too; the file form keeps it out of shell history.)
//
// Prints the cleared count only. The secret is never printed.
import { readFileSync } from 'node:fs';

const args = process.argv.slice(2);
let origin = 'https://auth.padiem.net';
const rest = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--origin') origin = args[++i];
  else rest.push(args[i]);
}
const [source] = rest;
if (!source || rest.length !== 1) {
  console.error('usage: node tools/reset-login-budget.mjs <address> [--origin URL]');
  process.exit(2);
}
let secret = process.env.PADIEM_AUTH_ADMIN_SECRET || '';
if (!secret && process.env.PADIEM_AUTH_ADMIN_SECRET_FILE) {
  secret = readFileSync(process.env.PADIEM_AUTH_ADMIN_SECRET_FILE, 'utf8').trim();
}
if (!secret) {
  console.error('admin secret missing: set PADIEM_AUTH_ADMIN_SECRET_FILE or PADIEM_AUTH_ADMIN_SECRET');
  process.exit(2);
}
const response = await fetch(new URL('/internal/login-failure-budget/reset', origin), {
  method: 'POST',
  headers: { authorization: `Bearer ${secret}`, 'content-type': 'application/json' },
  body: JSON.stringify({ source }),
});
let body = null;
try { body = await response.json(); } catch { /* status only */ }
if (response.status === 200 && body?.ok === true) {
  console.log(`LOGIN_BUDGET_RESET ok previous=${body.previous}`);
  process.exit(0);
}
const code = body?.error && typeof body.error === 'string' ? body.error : 'no_json_body';
console.error(`LOGIN_BUDGET_RESET failed status=${response.status} code=${code}`);
process.exit(1);
