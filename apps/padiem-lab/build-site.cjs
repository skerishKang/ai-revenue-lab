const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');
const labSource = path.join(repoRoot, 'apps', 'padiem-lab');
const out = path.join(repoRoot, 'dist', 'padiem-lab');
const staticAppSourceTreePins = Object.freeze({
  'apps/living-travel/pages-preview/site': 'fedd8846e3870661502ccb6947d8ed852eecc0b6'
});
const generatedSourceTreePins = Object.freeze({
  'apps/personal-edition': '8044c7a0fed5c6e9256a173e7633cb47dd7ba010',
  'apps/personal-video-archive': '580be319152fdf2001d979438b345e4172a2e2d4'
});

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

function sourceTreeAtHead(sourcePath) {
  return execFileSync('git', ['rev-parse', `HEAD:${sourcePath}`], {
    cwd: repoRoot,
    encoding: 'utf8'
  }).trim();
}

function isSafeRouteSource(route) {
  if (route.mode === 'STATIC_APP_PREVIEW') {
    return /^apps\/[a-z0-9-]+\/pages-preview(?:\/site)?$/.test(route.sourcePath);
  }
  if (route.mode === 'STATIC_APP_PREVIEW_ALLOWLIST') {
    return /^apps\/[a-z0-9-]+\/pages-preview\/site$/.test(route.sourcePath)
      && Boolean(staticAppSourceTreePins[route.sourcePath]);
  }
  if (route.mode === 'GENERATED_APP_PREVIEW' || route.mode === 'GENERATED_APP_PREVIEW_ALLOWLIST') {
    const common = /^apps\/[a-z0-9-]+$/.test(route.sourcePath)
      && /^scripts\.[a-z0-9_]+$/.test(route.generatorModule || '')
      && Boolean(generatedSourceTreePins[route.sourcePath]);
    if (!common) return false;
    if (route.mode === 'GENERATED_APP_PREVIEW_ALLOWLIST') {
      return /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(route.generatorOutputOverride || '')
        && Boolean(route.includeFiles?.length)
        && Boolean(route.includeDirs?.length);
    }
    return true;
  }
  return /^reference\/business-\d{2}-[^/]+$/.test(route.sourcePath);
}

function validateRegistry() {
  const numbers = new Set();
  const routeNames = new Set();
  for (const route of routes) {
    if (!Number.isInteger(route.number)) throw new Error(`Invalid Business number: ${route.number}`);
    const expected = `b${String(route.number).padStart(2, '0')}`;
    if (route.route !== expected) throw new Error(`Route mismatch for B${route.number}: ${route.route}`);
    if (numbers.has(route.number) || routeNames.has(route.route)) throw new Error(`Duplicate aggregate route: ${route.route}`);
    if (!isSafeRouteSource(route)) {
      throw new Error(`Unsafe source path for ${route.route}: ${route.sourcePath}`);
    }
    for (const header of route.aggregateHeaders || []) {
      if (!header || /[\r\n]/.test(header)) throw new Error(`Unsafe aggregate header for ${route.route}`);
    }
    for (const segment of route.privateLinkSegments || []) {
      if (!/^[a-z0-9-]+$/.test(segment)) throw new Error(`Unsafe private segment for ${route.route}: ${segment}`);
    }
    numbers.add(route.number);
    routeNames.add(route.route);
  }
}

function copyStaticReference(route, source, destination) {
  for (const name of route.includeFiles || []) {
    const target = path.join(source, name);
    requirePath(target);
    copyFile(target, path.join(destination, name));
  }
  for (const name of route.includeDirs || []) {
    const target = path.join(source, name);
    requirePath(target);
    copyDirectory(target, path.join(destination, name));
  }
}

function rewriteSubpathDependencies(route, destination) {
  const prefix = `/${route.route}/`;
  for (const file of walkFiles(destination).filter(file => /\.(?:html|css)$/i.test(file))) {
    let content = fs.readFileSync(file, 'utf8');
    content = content.replace(/((?:href|src|action)\s*=\s*["'])\/(?!\/)/gi, `$1${prefix}`);
    content = content.replace(/(url\(\s*["']?)\/(?!\/)/gi, `$1${prefix}`);
    content = content.replace(/(content\s*=\s*["'][^"']*url=)\/(?!\/)/gi, `$1${prefix}`);
    fs.writeFileSync(file, content, 'utf8');
  }
}

function copyStaticAppPreview(route, source, destination) {
  const excluded = new Set(route.excludeRootFiles || []);
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    if (excluded.has(entry.name)) continue;
    const sourceEntry = path.join(source, entry.name);
    const destinationEntry = path.join(destination, entry.name);
    if (entry.isDirectory()) copyDirectory(sourceEntry, destinationEntry);
    if (entry.isFile()) copyFile(sourceEntry, destinationEntry);
  }
  if (route.rewriteRootRelative) rewriteSubpathDependencies(route, destination);
}

function assertStaticAppSourcePin(route) {
  const expected = staticAppSourceTreePins[route.sourcePath];
  const actual = sourceTreeAtHead(route.sourcePath);
  if (actual !== expected) {
    throw new Error(`Pinned source tree changed for ${route.route}: expected ${expected}, got ${actual}`);
  }
}

function privateSegmentPattern(segments) {
  return segments.map(segment => segment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
}

function sanitizePrivateNavigation(route, destination) {
  if (!route.privateLinkSegments?.length) return;
  const alternation = privateSegmentPattern(route.privateLinkSegments);
  const anchor = new RegExp(`<a\\b(?=[^>]*\\bhref=["'][^"']*(?:${alternation})\\/)[^>]*>[\\s\\S]*?<\\/a>`, 'gi');
  const shellItem = new RegExp(`\\s*\\{\\s*key:\\s*["'](?:${alternation})["'][^}]*\\},?`, 'gi');

  for (const file of walkFiles(destination).filter(file => /\.(?:html|js)$/i.test(file))) {
    let content = fs.readFileSync(file, 'utf8');
    if (/\.html$/i.test(file)) content = content.replace(anchor, '');
    if (/\.js$/i.test(file)) content = content.replace(shellItem, '');
    fs.writeFileSync(file, content, 'utf8');
  }

  const privateUrl = new RegExp(`(?:href|src|action)\\s*=\\s*["'][^"']*(?:${alternation})\\/|href\\s*:\\s*["'][^"']*(?:${alternation})\\/`, 'i');
  for (const file of walkFiles(destination).filter(file => /\.(?:html|js)$/i.test(file))) {
    const content = fs.readFileSync(file, 'utf8');
    if (privateUrl.test(content)) {
      throw new Error(`Private navigation survived ${route.route} sanitization: ${path.relative(destination, file)}`);
    }
  }
}

function neutralizeStaticForms(route, destination) {
  if (!route.neutralizeForms) return;
  for (const file of walkFiles(destination).filter(file => /\.html$/i.test(file))) {
    let content = fs.readFileSync(file, 'utf8');
    content = content.replace(/<form\b([^>]*)>/gi, (_match, attrs) => {
      const stripped = attrs
        .replace(/\saction\s*=\s*(?:["'][^"']*["']|[^\s>]+)/gi, '')
        .replace(/\smethod\s*=\s*(?:["'][^"']*["']|[^\s>]+)/gi, '');
      return `<form${stripped} action="#" method="get">`;
    });
    fs.writeFileSync(file, content, 'utf8');
  }
}

function copyStaticAppPreviewAllowlist(route, source, destination) {
  assertStaticAppSourcePin(route);
  copyStaticReference(route, source, destination);
  sanitizePrivateNavigation(route, destination);
  neutralizeStaticForms(route, destination);
  if (route.rewriteRootRelative) rewriteSubpathDependencies(route, destination);
}

function assertGeneratedSourcePin(route) {
  const expected = generatedSourceTreePins[route.sourcePath];
  const actual = sourceTreeAtHead(route.sourcePath);
  if (actual !== expected) {
    throw new Error(`Pinned source tree changed for ${route.route}: expected ${expected}, got ${actual}`);
  }
  return expected;
}

function ensureGeneratedPreviewPython(route) {
  const sourceTree = generatedSourceTreePins[route.sourcePath];
  const tempRoot = process.env.RUNNER_TEMP || os.tmpdir();
  const venv = path.join(tempRoot, `padiem-lab-${route.route}-${sourceTree.slice(0, 12)}-venv`);
  const python = process.platform === 'win32'
    ? path.join(venv, 'Scripts', 'python.exe')
    : path.join(venv, 'bin', 'python');
  const ready = path.join(venv, '.padiem-preview-ready');

  if (!fs.existsSync(python)) {
    fs.rmSync(venv, { recursive: true, force: true });
    execFileSync(process.env.PREVIEW_BOOTSTRAP_PYTHON || 'python3', ['-m', 'venv', venv], {
      cwd: repoRoot,
      stdio: 'inherit'
    });
  }
  if (!fs.existsSync(ready) || fs.readFileSync(ready, 'utf8').trim() !== sourceTree) {
    execFileSync(python, [
      '-m', 'pip', 'install', '--disable-pip-version-check',
      'pydantic>=2.10,<3', 'jinja2>=3.1,<4'
    ], {
      cwd: repoRoot,
      stdio: 'inherit'
    });
    fs.writeFileSync(ready, sourceTree + '\n', 'utf8');
  }
  return python;
}

function generateStaticAppPreview(route, source, destination) {
  requirePath(path.join(source, 'pyproject.toml'));
  assertGeneratedSourcePin(route);
  const python = ensureGeneratedPreviewPython(route);
  const script = [
    'import importlib, sys',
    'from pathlib import Path',
    'module = importlib.import_module(sys.argv[1])',
    'module.main(Path(sys.argv[2]))'
  ].join('; ');
  execFileSync(python, ['-c', script, route.generatorModule, destination], {
    cwd: source,
    stdio: 'inherit'
  });
  requirePath(path.join(destination, 'index.html'));
  for (const name of route.excludeRootFiles || []) {
    fs.rmSync(path.join(destination, name), { recursive: true, force: true });
  }
  if (route.rewriteRootRelative) rewriteSubpathDependencies(route, destination);
}

function generateStaticAppPreviewAllowlist(route, source, destination) {
  requirePath(path.join(source, 'pyproject.toml'));
  const sourceTree = assertGeneratedSourcePin(route);
  const python = ensureGeneratedPreviewPython(route);
  const tempRoot = process.env.RUNNER_TEMP || os.tmpdir();
  const generated = path.join(tempRoot, `padiem-lab-${route.route}-${sourceTree.slice(0, 12)}-generated`);
  fs.rmSync(generated, { recursive: true, force: true });
  fs.mkdirSync(generated, { recursive: true });

  const script = [
    'import importlib, sys',
    'from pathlib import Path',
    'module = importlib.import_module(sys.argv[1])',
    'holder = module',
    'parts = sys.argv[3].split(".")',
    'for name in parts[:-1]:',
    '    holder = getattr(holder, name)',
    'setattr(holder, parts[-1], Path(sys.argv[2]))',
    'module.main()'
  ].join('\n');

  execFileSync(python, [
    '-c', script, route.generatorModule, generated, route.generatorOutputOverride
  ], {
    cwd: source,
    stdio: 'inherit'
  });

  requirePath(path.join(generated, 'index.html'));
  copyStaticReference(route, generated, destination);
  sanitizePrivateNavigation(route, destination);
  neutralizeStaticForms(route, destination);
  if (route.rewriteRootRelative) rewriteSubpathDependencies(route, destination);
  fs.rmSync(generated, { recursive: true, force: true });
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
  const forbiddenSegments = new Set([
    'operator', 'operations', 'collector', 'reviews', 'evidence', 'staging',
    ...(route.privateLinkSegments || [])
  ]);
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

function writeAggregateHeaders() {
  const sections = [];
  for (const route of routes) {
    if (!route.aggregateHeaders?.length) continue;
    sections.push(`/${route.route}/*\n${route.aggregateHeaders.map(header => `  ${header}`).join('\n')}`);
  }
  if (sections.length) {
    fs.writeFileSync(path.join(out, '_headers'), sections.join('\n\n') + '\n', 'utf8');
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
  } else if (route.mode === 'STATIC_APP_PREVIEW') {
    copyStaticAppPreview(route, source, destination);
  } else if (route.mode === 'STATIC_APP_PREVIEW_ALLOWLIST') {
    copyStaticAppPreviewAllowlist(route, source, destination);
  } else if (route.mode === 'GENERATED_APP_PREVIEW') {
    generateStaticAppPreview(route, source, destination);
  } else if (route.mode === 'GENERATED_APP_PREVIEW_ALLOWLIST') {
    generateStaticAppPreviewAllowlist(route, source, destination);
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
writeAggregateHeaders();

console.log(`Padiem Lab aggregate built at ${path.relative(repoRoot, out)}`);
console.log(`Included routes: /, ${routes.map(route => `/${route.route}/`).join(', ')}`);
