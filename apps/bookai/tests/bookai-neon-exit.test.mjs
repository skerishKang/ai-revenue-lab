import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publicRoot = path.join(appRoot, 'public');
const codeExtensions = new Set([
  '.js', '.mjs', '.cjs', '.html', '.css', '.json', '.sql',
  '.yml', '.yaml', '.toml', '.py', '.ts', '.tsx', '.jsx', '.sh'
]);
const configFiles = new Set([
  'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock',
  'bun.lock', 'bun.lockb', '.env.example'
]);

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (['.git', 'node_modules', 'tests'].includes(entry.name)) return [];
      return sourceFiles(full);
    }
    // This copied StoryMemory package checksum is archival metadata, not BookAI runtime/config.
    if (entry.name === 'MANIFEST_SHA256.json') return [];
    return codeExtensions.has(path.extname(entry.name).toLowerCase()) ||
      configFiles.has(entry.name) ? [full] : [];
  });
}

function assertHas(source, pattern, file, claim) {
  assert.ok(pattern.test(source), path.relative(appRoot, file) + ': ' + claim);
}

test('BookAI code has no Neon connection or provider configuration', () => {
  const connectionMarkers =
    /\bneon(?:js)?\b|@neondatabase|neon[.]tech|neonauth|\bDATABASE_URL\b|\b[A-Z0-9_]*NEON[A-Z0-9_]*\b|createStoryMemoryNeon|storyMemoryEnableNeon/i;
  for (const file of sourceFiles(appRoot)) {
    const source = fs.readFileSync(file, 'utf8');
    assert.ok(!connectionMarkers.test(source),
      path.relative(appRoot, file) + ' contains a removed remote provider marker');
  }
});

test('the reader page keeps the legacy remote lane disabled before fetch', () => {
  for (const page of [path.join(publicRoot, 'index.html')]) {
    const source = fs.readFileSync(page, 'utf8');
    assertHas(source, /const remoteEnabled = false;/, page, 'remote lane must stay disabled');
    const requestStart = source.indexOf('async function request(table');
    assert.notEqual(requestStart, -1, path.relative(appRoot, page) + ': request method is present');
    const disabledGuard = source.indexOf('if(!remoteEnabled)', requestStart);
    const networkCall = source.indexOf('fetchImpl(', requestStart);
    assert.ok(disabledGuard >= 0 && networkCall > disabledGuard,
      path.relative(appRoot, page) + ' must reject before fetch');
    assertHas(source, /remote:'disabled'/, page, 'status remains local');
    assertHas(source, /reason:'REMOTE_DISABLED'/, page, 'ping remains local');
    assertHas(source, /async function storyMemoryEnableRemote\(\)[\s\S]*?return \{ok:true,remote:'disabled'/,
      page, 'enableRemote resolves without enabling a provider');
    assertHas(source, /window\.BookAISync(?:\?\.|\.)syncNow\(/, page, 'account sync remains callable');
    assertHas(source, /remote:'disabled',accountSync/, page, 'sync returns a local result');
  }
});

test('remote pack and hybrid-memory surfaces stay disconnected while account sync remains available', () => {
  const shell = fs.readFileSync(path.join(publicRoot, 'index.html'), 'utf8');
  const hybrid = fs.readFileSync(path.join(publicRoot, 'storymemory-legacy-hybrid-ai-v1.js'), 'utf8');
  const sync = fs.readFileSync(path.join(publicRoot, 'bookai-sync.js'), 'utf8');
  const records = fs.readFileSync(path.join(publicRoot, 'bookai-records.js'), 'utf8');

  assertHas(hybrid, /async function remoteSnapshot\(\)\s*\{\s*return \{mode:'disabled'/,
    path.join(publicRoot, 'storymemory-legacy-hybrid-ai-v1.js'), 'remote Memory reads are disabled');
  assert.ok(!/remoteAdapter|\.request\(/.test(hybrid), 'hybrid AI must not call a remote adapter');
  assertHas(sync, /const db = root\.BookAILocalDB, endpoint = '\/api\/bookai\/records';/,
    path.join(publicRoot, 'bookai-sync.js'), 'account sync uses the records API');
  assertHas(records, /'progress','note','highlight','ai_chat'/,
    path.join(publicRoot, 'bookai-records.js'), 'reader and saved-chat records stay mappable');
});

test('removed pack surfaces leave no files or references behind', () => {
  const removed = [
    'storymemory-pack-marketplace-runtime.js',
    'storymemory-pack-marketplace-ui.js',
    'storymemory-pack-marketplace-ui.css',
    'storymemory-auto-pack-runtime.js',
    'storymemory-auto-pack-ui.js',
    'storymemory-auto-pack-ui.css',
    'storymemory-pack-lifecycle-runtime.js',
    'storymemory-pack-lifecycle-ui.js',
    'storymemory-pack-lifecycle-ui.css',
    'storymemory-pack-entitlement-runtime.js',
    'storymemory-pack-entitlement-ui.js',
    'storymemory-pack-entitlement-ui.css',
    'storymemory-pack-verification-runtime.js',
    'storymemory-pack-verification-ui.js',
    'storymemory-pack-verification-ui.css',
    'mobile-source-settings.js',
  ];
  for (const name of removed) {
    assert.ok(!fs.existsSync(path.join(publicRoot, name)), name + ' must be deleted');
  }
  const references = [];
  for (const file of sourceFiles(publicRoot)) {
    const source = fs.readFileSync(file, 'utf8');
    for (const name of removed) {
      if (source.includes(name)) references.push(path.relative(publicRoot, file) + ': ' + name);
    }
  }
  assert.deepEqual(references, [], 'removed pack surfaces must not be referenced');
  const shell = fs.readFileSync(path.join(publicRoot, 'index.html'), 'utf8');
  assert.ok(!shell.includes('bookai-remote-pack-surfaces-disabled'), 'pack-hiding style must be gone');
  assert.ok(!/#packMarketplaceLaunch|#autoPackLaunch|#packEntitlementLaunch|#packVerificationLaunch/.test(shell),
    'pack launch ids must be gone from the shell');
});
