const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');
const out = path.join(repoRoot, 'dist', 'padiem-lab');

function build() {
  execFileSync(process.execPath, [path.join(__dirname, 'build-site.cjs')], {
    cwd: repoRoot,
    stdio: 'pipe'
  });
}

function routeOut(route) {
  return path.join(out, route.route);
}

function walkFiles(root) {
  const files = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const target = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...walkFiles(target));
    if (entry.isFile()) files.push(target);
  }
  return files;
}

test('route registry has unique exact /bNN/ identities for Batch A and B60', () => {
  const numbers = routes.map(route => route.number);
  const names = routes.map(route => route.route);
  assert.equal(new Set(numbers).size, numbers.length);
  assert.equal(new Set(names).size, names.length);
  assert.deepEqual(numbers, [7, 8, 9, 10, 60]);
  for (const route of routes) {
    assert.equal(route.route, `b${String(route.number).padStart(2, '0')}`);
    assert.match(route.sourcePath, /^reference\/business-\d{2}-[^/]+$/);
    assert.ok(route.marker);
  }
});

test('aggregate build contains Lab shell and every registered Business route', () => {
  build();
  for (const file of [
    path.join(out, 'index.html'),
    path.join(out, '404.html'),
    path.join(out, 'styles.css'),
    path.join(out, 'app.js'),
    path.join(out, 'public-businesses.js')
  ]) {
    assert.equal(fs.existsSync(file), true, `missing ${path.relative(repoRoot, file)}`);
  }

  for (const route of routes) {
    const target = routeOut(route);
    assert.equal(fs.existsSync(path.join(target, 'index.html')), true, `missing /${route.route}/index.html`);
    const html = fs.readFileSync(path.join(target, 'index.html'), 'utf8');
    assert.match(html, new RegExp(route.marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  const notFound = fs.readFileSync(path.join(out, '404.html'), 'utf8');
  assert.match(notFound, /페이지를 찾을 수 없습니다/);
  assert.match(notFound, /noindex/);
});

test('static reference routes publish only runtime allowlists', () => {
  build();
  for (const route of routes.filter(route => route.mode === 'STATIC_REFERENCE')) {
    const target = routeOut(route);
    for (const file of ['index.html', 'guide.html', 'ux.html']) {
      assert.equal(fs.existsSync(path.join(target, file)), true, `${route.route} missing ${file}`);
    }
    for (const directory of ['assets', 'scripts', 'styles']) {
      assert.equal(fs.existsSync(path.join(target, directory)), true, `${route.route} missing ${directory}/`);
    }
    for (const forbidden of ['README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence']) {
      assert.equal(fs.existsSync(path.join(target, forbidden)), false, `${route.route} leaked ${forbidden}`);
    }
  }
});

test('aggregate runtime excludes repository-only and private paths recursively', () => {
  build();
  const forbiddenSegments = new Set(['operator', 'operations', 'collector', 'reviews', 'evidence']);
  for (const route of routes) {
    for (const file of walkFiles(routeOut(route))) {
      const relative = path.relative(routeOut(route), file);
      assert.equal(relative.endsWith('.md'), false, `${route.route} leaked markdown: ${relative}`);
      assert.equal(relative.endsWith('.test.cjs'), false, `${route.route} leaked test: ${relative}`);
      assert.equal(relative.split(path.sep).some(segment => forbiddenSegments.has(segment)), false, `${route.route} leaked private path: ${relative}`);
    }
  }
});

test('Batch A static runtime files are safe under a /bNN/ subpath', () => {
  build();
  const unsafeRootReference = /(?:href|src)\s*=\s*["']\/(?!\/)|url\(\s*["']?\/(?!\/)/i;
  for (const route of routes.filter(route => route.mode === 'STATIC_REFERENCE')) {
    for (const file of walkFiles(routeOut(route)).filter(file => /\.(?:html|css|js)$/i.test(file))) {
      const content = fs.readFileSync(file, 'utf8');
      assert.doesNotMatch(content, unsafeRootReference, `${route.route} has root-relative dependency in ${path.relative(routeOut(route), file)}`);
    }
  }
});

test('B60 runtime dependencies keep assets and data together under /b60/', () => {
  build();
  const b60 = path.join(out, 'b60');
  assert.equal(fs.existsSync(path.join(b60, 'assets')), true);
  assert.equal(fs.existsSync(path.join(b60, 'data')), true);
  assert.equal(fs.existsSync(path.join(b60, 'product-v13-editorial-radar.js')), true);
  assert.equal(fs.existsSync(path.join(b60, 'product-v14-opportunity-detail.js')), true);
  const html = fs.readFileSync(path.join(b60, 'index.html'), 'utf8');
  assert.match(html, /data\/editorial-opportunities\.js/);
  assert.match(html, /product-v13-editorial-radar\.js/);
  assert.match(html, /product-v14-opportunity-detail\.js/);
});

test('aggregate redirects canonicalize every /bNN route to trailing slash', () => {
  build();
  const redirects = fs.readFileSync(path.join(out, '_redirects'), 'utf8');
  for (const route of routes) {
    assert.match(redirects, new RegExp(`^/${route.route} /${route.route}/ 301$`, 'm'));
  }
});
