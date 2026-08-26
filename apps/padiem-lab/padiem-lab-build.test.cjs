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

function rootReferences(content) {
  const references = [];
  for (const match of content.matchAll(/(?:href|src|action)\s*=\s*["'](\/(?!\/)[^"']*)["']/gi)) {
    references.push(match[1]);
  }
  for (const match of content.matchAll(/url\(\s*["']?(\/(?!\/)[^"')\s]*)/gi)) {
    references.push(match[1]);
  }
  return references;
}

test('route registry has unique exact /bNN/ identities for routed static Businesses and B60', () => {
  const numbers = routes.map(route => route.number);
  const names = routes.map(route => route.route);
  assert.equal(new Set(numbers).size, numbers.length);
  assert.equal(new Set(names).size, names.length);
  assert.deepEqual(numbers, [2, 4, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22, 60]);
  for (const route of routes) {
    assert.equal(route.route, `b${String(route.number).padStart(2, '0')}`);
    if (route.mode === 'STATIC_APP_PREVIEW') {
      assert.match(route.sourcePath, /^apps\/[a-z0-9-]+\/pages-preview(?:\/site)?$/);
    } else if (route.mode === 'STATIC_APP_PREVIEW_ALLOWLIST') {
      assert.match(route.sourcePath, /^apps\/[a-z0-9-]+\/pages-preview\/site$/);
      assert.ok(route.includeFiles?.length);
      assert.ok(route.includeDirs?.length);
      assert.ok(route.privateLinkSegments?.length);
    } else if (route.mode === 'GENERATED_APP_PREVIEW') {
      assert.match(route.sourcePath, /^apps\/[a-z0-9-]+$/);
      assert.match(route.generatorModule, /^scripts\.[a-z0-9_]+$/);
    } else {
      assert.match(route.sourcePath, /^reference\/business-\d{2}-[^/]+$/);
    }
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

test('static reference routes publish exactly their route-specific runtime allowlists', () => {
  build();
  for (const route of routes.filter(route => route.mode === 'STATIC_REFERENCE')) {
    const target = routeOut(route);
    for (const file of route.includeFiles || []) {
      assert.equal(fs.existsSync(path.join(target, file)), true, `${route.route} missing ${file}`);
    }
    for (const directory of route.includeDirs || []) {
      assert.equal(fs.existsSync(path.join(target, directory)), true, `${route.route} missing ${directory}/`);
    }
    for (const excluded of route.excludePaths || []) {
      assert.equal(fs.existsSync(path.join(target, excluded)), false, `${route.route} leaked excluded path ${excluded}`);
    }
    for (const forbidden of ['README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence']) {
      assert.equal(fs.existsSync(path.join(target, forbidden)), false, `${route.route} leaked ${forbidden}`);
    }
  }
});

test('B02 publishes only pinned Living Travel customer/demo preview surfaces', () => {
  build();
  const b02 = path.join(out, 'b02');
  for (const relative of [
    'index.html',
    'guide.html',
    'robots.txt',
    'assets/style.css',
    'assets/b2-shell-20260810.js',
    'demo/intro.html',
    'demo/preferences.html',
    'demo/pending.html',
    'demo/traveler-home.html',
    'demo/edition.html',
    'demo/history.html',
    'traveler/enter.html',
    'traveler/dashboard.html',
    'traveler/edition.html',
    'traveler/history.html'
  ]) {
    assert.equal(fs.existsSync(path.join(b02, relative)), true, `b02 missing ${relative}`);
  }
  for (const forbidden of ['_headers', 'operator', 'staging']) {
    assert.equal(fs.existsSync(path.join(b02, forbidden)), false, `b02 leaked ${forbidden}`);
  }

  const privateNavigation = /(?:href|src|action)\s*=\s*["'][^"']*(?:operator|staging)\/|href\s*:\s*["'][^"']*(?:operator|staging)\//i;
  for (const file of walkFiles(b02).filter(file => /\.(?:html|js)$/i.test(file))) {
    const content = fs.readFileSync(file, 'utf8');
    assert.doesNotMatch(content, privateNavigation, `b02 retained private navigation in ${path.relative(b02, file)}`);
  }

  const index = fs.readFileSync(path.join(b02, 'index.html'), 'utf8');
  assert.match(index, /Living Travel/);
  assert.match(index, /noindex,nofollow/);
  assert.doesNotMatch(index, /operator\/login\.html/i);
  const shell = fs.readFileSync(path.join(b02, 'assets', 'b2-shell-20260810.js'), 'utf8');
  assert.doesNotMatch(shell, /operator\/login\.html|key:\s*["']operator["']/i);

  const headers = fs.readFileSync(path.join(out, '_headers'), 'utf8');
  assert.match(headers, /^\/b02\/\*$/m);
  assert.match(headers, /X-Robots-Tag: noindex, nofollow/);
  assert.match(headers, /connect-src 'none'/);
  assert.match(headers, /form-action 'none'/);
});

test('B04 publishes only the Living Learning static preview under its subpath', () => {
  build();
  const b04 = path.join(out, 'b04');
  for (const relative of [
    'index.html',
    'guide.html',
    'assets',
    'goals/index.html',
    'diagnostic/index.html',
    'lesson-1/index.html',
    'lesson-2/index.html',
    'feedback/index.html',
    'history/index.html',
    'progress/index.html',
    'review/index.html'
  ]) {
    assert.equal(fs.existsSync(path.join(b04, relative)), true, `b04 missing ${relative}`);
  }
  assert.equal(fs.existsSync(path.join(b04, '_headers')), false, 'b04 leaked child _headers');
  assert.equal(fs.existsSync(path.join(b04, '_redirects')), false, 'b04 leaked child _redirects');
  assert.equal(fs.existsSync(path.join(b04, 'app')), false, 'b04 leaked backend app');
  assert.equal(fs.existsSync(path.join(b04, 'migrations')), false, 'b04 leaked migrations');

  const index = fs.readFileSync(path.join(b04, 'index.html'), 'utf8');
  assert.match(index, /href="\/b04\/assets\/css\/tokens\.css"/);
  assert.match(index, /href="\/b04\/guide\.html"/);
  assert.match(index, /href="\/b04\/goals\/"/);
  assert.match(index, /href="\/b04\/review\/"/);
  assert.match(index, /UI Preview/);
  assert.match(index, /No persistence/);
});

test('B13 is generated from the existing Personal Video Archive static-preview boundary only', () => {
  build();
  const b13 = path.join(out, 'b13');
  for (const relative of [
    'index.html',
    'en/index.html',
    'preview-states/index.html',
    'topics/index.html',
    'topics/pv-topic-0001/index.html',
    'videos/pv-video-0001/index.html',
    'records/pv-rec-0001/index.html',
    'static/style.css',
    'robots.txt'
  ]) {
    assert.equal(fs.existsSync(path.join(b13, relative)), true, `b13 missing ${relative}`);
  }
  for (const forbidden of ['_headers', 'app', 'scripts', 'tests', 'preview_fixtures', 'pyproject.toml']) {
    assert.equal(fs.existsSync(path.join(b13, forbidden)), false, `b13 leaked source/runtime path ${forbidden}`);
  }
  assert.equal(walkFiles(b13).some(file => file.endsWith('.py')), false, 'b13 leaked Python source');

  const index = fs.readFileSync(path.join(b13, 'index.html'), 'utf8');
  assert.match(index, /Business 13/);
  assert.match(index, /noindex,nofollow/);
  assert.match(index, /href="\/b13\/static\/style\.css"/);
  assert.doesNotMatch(index, /<script\b/i);
  assert.doesNotMatch(index, /\son[a-z]+\s*=/i);

  const headers = fs.readFileSync(path.join(out, '_headers'), 'utf8');
  assert.match(headers, /^\/b13\/\*$/m);
  assert.match(headers, /X-Robots-Tag: noindex, nofollow/);
  assert.match(headers, /script-src 'none'/);
  assert.match(headers, /form-action 'none'/);
});

test('B06 publishes its single-app World Feed shape without inventing a ux entry', () => {
  build();
  const b06 = path.join(out, 'b06');
  assert.equal(fs.existsSync(path.join(b06, 'index.html')), true);
  assert.equal(fs.existsSync(path.join(b06, 'guide.html')), true);
  assert.equal(fs.existsSync(path.join(b06, 'assets')), true);
  assert.equal(fs.existsSync(path.join(b06, 'scripts')), true);
  assert.equal(fs.existsSync(path.join(b06, 'styles')), true);
  assert.equal(fs.existsSync(path.join(b06, 'ux.html')), false, 'b06 invented a ux.html entry');
});

test('explicit current-executable routes omit legacy root app and docs surfaces', () => {
  build();
  for (const number of [16, 18, 19, 20, 22]) {
    const route = routes.find(candidate => candidate.number === number);
    assert.ok(route, `missing B${number} route`);
    const target = routeOut(route);
    for (const file of ['index.html', 'guide.html', 'ux.html']) {
      assert.equal(fs.existsSync(path.join(target, file)), true, `${route.route} missing ${file}`);
    }
    assert.equal(fs.existsSync(path.join(target, 'assets')), true, `${route.route} missing assets`);
    assert.equal(fs.existsSync(path.join(target, 'styles')), true, `${route.route} missing styles`);
    assert.equal(fs.existsSync(path.join(target, 'app.js')), false, `${route.route} leaked root legacy app.js`);
    assert.equal(fs.existsSync(path.join(target, 'docs')), false, `${route.route} leaked docs`);
  }
});

test('aggregate runtime excludes repository-only and private paths recursively', () => {
  build();
  const forbiddenSegments = new Set(['operator', 'operations', 'collector', 'reviews', 'evidence', 'staging']);
  for (const route of routes) {
    for (const file of walkFiles(routeOut(route))) {
      const relative = path.relative(routeOut(route), file);
      assert.equal(relative.endsWith('.md'), false, `${route.route} leaked markdown: ${relative}`);
      assert.equal(relative.endsWith('.test.cjs'), false, `${route.route} leaked test: ${relative}`);
      assert.equal(relative.endsWith('.py'), false, `${route.route} leaked Python: ${relative}`);
      assert.equal(relative.split(path.sep).some(segment => forbiddenSegments.has(segment)), false, `${route.route} leaked private path: ${relative}`);
    }
  }
});

test('all local static runtime files stay inside their own /bNN/ subpath', () => {
  build();
  const localModes = new Set(['STATIC_REFERENCE', 'STATIC_APP_PREVIEW', 'STATIC_APP_PREVIEW_ALLOWLIST', 'GENERATED_APP_PREVIEW']);
  for (const route of routes.filter(route => localModes.has(route.mode))) {
    const allowedPrefix = `/${route.route}/`;
    for (const file of walkFiles(routeOut(route)).filter(file => /\.(?:html|css|js)$/i.test(file))) {
      const content = fs.readFileSync(file, 'utf8');
      for (const reference of rootReferences(content)) {
        assert.equal(
          reference === allowedPrefix || reference.startsWith(allowedPrefix),
          true,
          `${route.route} escaped its route in ${path.relative(routeOut(route), file)}: ${reference}`
        );
      }
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
