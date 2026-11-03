import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publicRoot = path.join(appRoot, 'public');
const codeExtensions = new Set(['.js', '.mjs', '.cjs', '.html', '.css', '.json', '.sql']);

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (['.git', 'node_modules', 'tests'].includes(entry.name)) return [];
      return sourceFiles(full);
    }
    return codeExtensions.has(path.extname(entry.name).toLowerCase()) ? [full] : [];
  });
}

function assertHas(source, pattern, file, claim) {
  assert.ok(pattern.test(source), `${path.relative(appRoot, file)}: ${claim}`);
}

test('BookAI runtime source has no Neon endpoint or adapter configuration', () => {
  const forbidden = /\bneon\b|neon[.]tech|neonauth|us-east-1|createStoryMemoryNeon|storyMemoryEnableNeon/i;
  for (const file of sourceFiles(appRoot)) {
    const source = fs.readFileSync(file, 'utf8');
    assert.ok(!forbidden.test(source),
      `${path.relative(appRoot, file)} contains a removed remote provider marker`);
  }
});

test('both reader pages keep the legacy remote lane disabled before fetch', () => {
  for (const page of [
    path.join(publicRoot, 'index.html'),
    path.join(publicRoot, 'readback_index.html', 'index.html')
  ]) {
    const source = fs.readFileSync(page, 'utf8');
    assertHas(source, /const remoteEnabled = false;/, page, 'remote lane must stay disabled');
    assertHas(source, /bookai-remote-pack-surfaces-disabled/, page, 'remote pack surfaces are hidden');
    const requestStart = source.indexOf('async function request(table');
    assert.notEqual(requestStart, -1, `${path.relative(appRoot, page)}: request method is present`);
    const disabledGuard = source.indexOf('if(!remoteEnabled)', requestStart);
    const networkCall = source.indexOf('fetchImpl(', requestStart);
    assert.ok(disabledGuard >= 0 && networkCall > disabledGuard,
      `${path.relative(appRoot, page)} must reject before fetch`);
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

  assertHas(shell, /bookai-remote-pack-surfaces-disabled/, path.join(publicRoot, 'index.html'), 'remote pack UI is hidden');
  assertHas(hybrid, /async function remoteSnapshot\(\)\s*\{\s*return \{mode:'disabled'/,
    path.join(publicRoot, 'storymemory-legacy-hybrid-ai-v1.js'), 'remote Memory reads are disabled');
  assert.ok(!/remoteAdapter|\.request\(/.test(hybrid), 'hybrid AI must not call a remote adapter');
  assertHas(sync, /const db = root\.BookAILocalDB, endpoint = '\/api\/bookai\/records';/,
    path.join(publicRoot, 'bookai-sync.js'), 'account sync uses the records API');
  assertHas(records, /'progress','note','highlight','ai_chat'/,
    path.join(publicRoot, 'bookai-records.js'), 'reader and saved-chat records stay mappable');
});
