const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..', '..');
const labSource = path.join(repoRoot, 'apps', 'padiem-lab');
const b60Source = path.join(repoRoot, 'reference', 'business-60-ai-api-v1');
const out = path.join(repoRoot, 'dist', 'padiem-lab');
const b60Out = path.join(out, 'b60');

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

requirePath(path.join(labSource, 'index.html'));
requirePath(path.join(b60Source, 'index.html'));

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

for (const name of ['index.html', 'styles.css', 'app.js', 'public-businesses.js']) {
  copyFile(path.join(labSource, name), path.join(out, name));
}

fs.mkdirSync(b60Out, { recursive: true });
for (const entry of fs.readdirSync(b60Source, { withFileTypes: true })) {
  if (entry.isFile()) {
    if (entry.name === 'index.html' || entry.name.endsWith('.css') || entry.name.endsWith('.js')) {
      copyFile(path.join(b60Source, entry.name), path.join(b60Out, entry.name));
    }
    continue;
  }

  if (entry.isDirectory() && ['assets', 'data'].includes(entry.name)) {
    copyDirectory(path.join(b60Source, entry.name), path.join(b60Out, entry.name));
  }
}

fs.writeFileSync(
  path.join(out, '_redirects'),
  '/b60 /b60/ 301\n',
  'utf8'
);

const forbidden = ['operator', 'operations', 'collector', 'reviews'];
for (const name of forbidden) {
  if (fs.existsSync(path.join(b60Out, name))) {
    throw new Error(`Forbidden B60 non-public directory entered aggregate artifact: ${name}`);
  }
}

for (const entry of fs.readdirSync(b60Out)) {
  if (entry.endsWith('.test.cjs') || entry.endsWith('.md')) {
    throw new Error(`Non-runtime B60 file entered aggregate artifact: ${entry}`);
  }
}

console.log(`Padiem Lab aggregate built at ${path.relative(repoRoot, out)}`);
console.log('Included routes: /, /b60/');
