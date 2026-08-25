const fs = require('node:fs');
const path = require('node:path');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');
const labSource = path.join(repoRoot, 'apps', 'padiem-lab');
const out = path.join(repoRoot, 'dist', 'padiem-lab');

function copyFile(source, destination) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.copyFileSync(source, destination);
}

function copyDirectory(source, destination) {
  fs.cpSync(source, destination, { recursive: true, force: true });
}

function requirePath(target) {
  if (!fs.existsSync(target)) {
    throw new Error(`Required deployment source is missing: ${path.relative(repoRoot, target)}`);
  }
}

function validateRegistry() {
  const numbers = new Set();
  const routeNames = new Set();
  for (const route of routes) {
    if (!Number.isInteger(route.number)) throw new Error(`Invalid Business number: ${route.number}`);
    const expected = `b${String(route.number).padStart(2, '0')}`;
    if (route.route !== expected) throw new Error(`Route mismatch for B${route.number}: ${route.route}`);
    if (numbers.has(route.number) || routeNames.has(route.route)) throw new Error(`Duplicate aggregate route: ${route.route}`);
    if (!/^reference\/business-\d{2}-[^/]+$/.test(route.sourcePath)) {
      throw new Error(`Unsafe source path for ${route.route}: ${route.sourcePath}`);
    }
    numbers.add(route.number);
    routeNames.add(route.route);
  }
}

function copyStaticReference(route, source, destination) {
  for (const name of route.includeFiles) {
    const target = path.join(source, name);
    requirePath(target);
    copyFile(target, path.join(destination, name));
  }
  for (const name of route.includeDirs) {
    const target = path.join(source, name);
    requirePath(target);
    copyDirectory(target, path.join(destination, name));
  }
}

function copyB60Public(route, source, destination) {
  requirePath(path.join(source, 'index.html'));
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    if (entry.isFile()) {
      if (entry.name === 'index.html' || entry.name.endsWith('.css') || entry.name.endsWith('.js')) {
        copyFile(path.join(source, entry.name), path.join(destination, entry.name));
      }
      continue;
    }
    if (entry.isDirectory() && route.includeDirs.includes(entry.name)) {
      copyDirectory(path.join(source, entry.name), path.join(destination, entry.name));
    }
  }
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

function assertPublicBoundary(route, destination) {
  const forbiddenSegments = new Set(['operator', 'operations', 'collector', 'reviews', 'evidence']);
  for (const file of walkFiles(destination)) {
    const relative = path.relative(destination, file);
    const segments = relative.split(path.sep);
    if (segments.some(segment => forbiddenSegments.has(segment))) {
      throw new Error(`Forbidden ${route.route} non-public path entered aggregate artifact: ${relative}`);
    }
    if (relative.endsWith('.test.cjs') || relative.endsWith('.md')) {
      throw new Error(`Repository-only ${route.route} file entered aggregate artifact: ${relative}`);
    }
  }
}

validateRegistry();
requirePath(path.join(labSource, 'index.html'));
requirePath(path.join(labSource, '404.html'));

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

for (const name of ['index.html', '404.html', 'styles.css', 'app.js', 'public-businesses.js']) {
  copyFile(path.join(labSource, name), path.join(out, name));
}

for (const route of routes) {
  const source = path.join(repoRoot, route.sourcePath);
  const destination = path.join(out, route.route);
  requirePath(source);
  fs.mkdirSync(destination, { recursive: true });

  if (route.mode === 'STATIC_REFERENCE') {
    copyStaticReference(route, source, destination);
  } else if (route.mode === 'B60_PUBLIC_ALLOWLIST') {
    copyB60Public(route, source, destination);
  } else {
    throw new Error(`Unsupported aggregate route mode: ${route.mode}`);
  }

  assertPublicBoundary(route, destination);
}

fs.writeFileSync(
  path.join(out, '_redirects'),
  routes.map(route => `/${route.route} /${route.route}/ 301`).join('\n') + '\n',
  'utf8'
);

console.log(`Padiem Lab aggregate built at ${path.relative(repoRoot, out)}`);
console.log(`Included routes: /, ${routes.map(route => `/${route.route}/`).join(', ')}`);
