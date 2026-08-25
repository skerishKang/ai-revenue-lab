const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const test = require('node:test');

const repoRoot = path.resolve(__dirname, '..', '..');
const out = path.join(repoRoot, 'dist', 'padiem-lab');
const b60 = path.join(out, 'b60');

function build() {
  execFileSync(process.execPath, [path.join(__dirname, 'build-site.cjs')], {
    cwd: repoRoot,
    stdio: 'pipe'
  });
}

test('aggregate build contains public Lab root and B60 route', () => {
  build();
  for (const file of [
    path.join(out, 'index.html'),
    path.join(out, 'styles.css'),
    path.join(out, 'app.js'),
    path.join(out, 'public-businesses.js'),
    path.join(b60, 'index.html'),
    path.join(b60, 'product-v13-editorial-radar.js'),
    path.join(b60, 'product-v14-opportunity-detail.js')
  ]) {
    assert.equal(fs.existsSync(file), true, `missing ${path.relative(repoRoot, file)}`);
  }
});

test('B60 aggregate artifact excludes operator and repository-only material', () => {
  build();
  for (const name of ['operator', 'operations', 'collector', 'reviews']) {
    assert.equal(fs.existsSync(path.join(b60, name)), false, `${name} must not be public`);
  }
  const rootNames = fs.readdirSync(b60);
  assert.equal(rootNames.some(name => name.endsWith('.test.cjs')), false);
  assert.equal(rootNames.some(name => name.endsWith('.md')), false);
});

test('B60 runtime dependencies keep assets and data together under /b60/', () => {
  build();
  assert.equal(fs.existsSync(path.join(b60, 'assets')), true);
  assert.equal(fs.existsSync(path.join(b60, 'data')), true);
  const html = fs.readFileSync(path.join(b60, 'index.html'), 'utf8');
  assert.match(html, /data\/editorial-opportunities\.js/);
  assert.match(html, /product-v13-editorial-radar\.js/);
  assert.match(html, /product-v14-opportunity-detail\.js/);
});

test('aggregate route canonicalizes /b60 to /b60/', () => {
  build();
  const redirects = fs.readFileSync(path.join(out, '_redirects'), 'utf8');
  assert.match(redirects, /^\/b60 \/b60\/ 301/m);
});
