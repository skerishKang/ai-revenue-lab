// Version-stamps the DEPLOY COPY of the static tree — never repository files.
//
// index.html references app.js, locale.js, styles.css and ~130 other local
// assets with unversioned relative URLs. After a deploy an already-open tab
// (and some mobile browsers) keep running the old JS against a new server.
// Stamping every local script/link reference with ?v=<8-char release sha>
// makes each deploy a fresh cache key: the next navigation re-fetches
// index.html (never cached) and every asset URL in it is one no browser has.
//
// Static files are ALSO loaded from outside index.html: JS lazily injects
// <script>/<link> elements from string literals (a11y.js, theme-init.js,
// util-pdfmd.js, ...) and CSS pulls sheets and images via @import/url().
// Those literals must carry the same version or the browser reuses the old
// bytes. The tree pass rewrites the matching literals in the deploy copies of
// *.js and *.css. A literal is only rewritten when its FULL text is a local
// asset path whose target exists in the stamped tree, so API paths, external
// URLs and unrelated strings are never touched. The rewrite is uniform, which
// is what keeps the dedupe querySelectors working:
// document.querySelector('link[href="./pc-file-exchange.css"]') and the
// assignment css.href = "./pc-file-exchange.css" gain the same ?v= together.
//
// Usage:
//   node stamp_index_html.mjs <dir> <version>        stamp <dir> (html + js/css) in place
//   node stamp_index_html.mjs --check <dir> <version> exit 0 when everything is stamped
//
// The release script (release_chat.ps1) stamps a copy extracted from the
// pinned SHA and ships it via the wrangler `--assets` override; the pages
// build (apps/padiem-chat-pages/build.mjs) reuses stampStaticTree() on dist/.
import { existsSync } from "node:fs";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const VERSION_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/;
const TAG_REFERENCE = /(<(?:script|link)\b[^>]*?\b(?:src|href)=)(["'])([^"']+?)\2/gi;
// Full string literals only: same quote, no escapes, no newlines. Template
// literals stay untouched — no static asset path is built by interpolation.
const JS_LITERAL = /(["'])([^"'\\\n]+)\1/g;
const CSS_URL = /url\(\s*(["']?)([^"')\s]+)\1\s*\)/gi;
const CSS_IMPORT = /@import\s+(["'])([^"'\n]+)\1/g;
const ASSET_EXTENSION = /\.(?:js|css|png|jpe?g|svg|webp|ico|woff2?|webmanifest)$/i;

function isLocalReference(value) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(value)) return false; // data:, https:, //host, #anchor
  return value.trim().length > 0;
}

function assetBase(value) {
  // Re-stamping replaces a previous ?v= token; other query strings are
  // collapsed to the version query (none exist today) so the operation stays
  // predictable and the dedupe checks keep matching the assignments.
  return value.includes("?") ? value.slice(0, value.indexOf("?")) : value;
}

// A reference is stamped only when the target file exists in the tree being
// stamped (relative to the referencing file; root-absolute from the root).
function makeResolver(rootDir, fileDir) {
  return (reference) => {
    if (!ASSET_EXTENSION.test(assetBase(reference))) return false;
    const target = path.resolve(
      reference.startsWith("/") ? rootDir : fileDir,
      reference.startsWith("/") ? reference.slice(1) : reference.replace(/^\.\//, ""),
    );
    if (target !== rootDir && !target.startsWith(rootDir + path.sep)) return false;
    return existsSync(target);
  };
}

export function stampIndexHtml(html, version) {
  if (!VERSION_PATTERN.test(version)) {
    throw new Error(`invalid asset version: ${JSON.stringify(version)}`);
  }
  let stamped = 0;
  const rewritten = html.replace(TAG_REFERENCE, (whole, lead, quote, value) => {
    if (!isLocalReference(value)) return whole;
    stamped += 1;
    return `${lead}${quote}${assetBase(value)}?v=${version}${quote}`;
  });
  return { html: rewritten, stamped };
}

export function stampJsAssetReferences(text, version, exists) {
  if (!VERSION_PATTERN.test(version)) {
    throw new Error(`invalid asset version: ${JSON.stringify(version)}`);
  }
  let stamped = 0;
  const rewritten = text.replace(JS_LITERAL, (whole, quote, value) => {
    if (!isLocalReference(value) || !exists(assetBase(value))) return whole;
    stamped += 1;
    return `${quote}${assetBase(value)}?v=${version}${quote}`;
  });
  return { text: rewritten, stamped };
}

export function stampCssAssetReferences(text, version, exists) {
  if (!VERSION_PATTERN.test(version)) {
    throw new Error(`invalid asset version: ${JSON.stringify(version)}`);
  }
  let stamped = 0;
  let out = text.replace(CSS_URL, (whole, quote, value) => {
    if (!isLocalReference(value) || !exists(assetBase(value))) return whole;
    stamped += 1;
    return `url(${quote}${assetBase(value)}?v=${version}${quote})`;
  });
  out = out.replace(CSS_IMPORT, (whole, quote, value) => {
    if (!isLocalReference(value) || !exists(assetBase(value))) return whole;
    stamped += 1;
    return `@import ${quote}${assetBase(value)}?v=${version}${quote}`;
  });
  return { text: out, stamped };
}

async function collectCodeFiles(rootDir) {
  const found = [];
  async function walk(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (/\.(?:html|js|css)$/i.test(entry.name)) found.push(full);
    }
  }
  await walk(rootDir);
  return found;
}

function stampFile(file, original, version, exists) {
  if (file.endsWith(".html")) {
    const { html, stamped } = stampIndexHtml(original, version);
    return { text: html, stamped, html: true };
  }
  if (file.endsWith(".js")) {
    const { text, stamped } = stampJsAssetReferences(original, version, exists);
    return { text, stamped, html: false };
  }
  if (file.endsWith(".css")) {
    const { text, stamped } = stampCssAssetReferences(original, version, exists);
    return { text, stamped, html: false };
  }
  return { text: original, stamped: 0, html: false };
}

// Stamps every HTML entry and every JS/CSS asset literal in the deploy copy.
export async function stampStaticTree(dir, version) {
  if (!VERSION_PATTERN.test(version)) {
    throw new Error(`invalid asset version: ${JSON.stringify(version)}`);
  }
  const root = path.resolve(dir);
  const result = { htmlRefs: 0, assetRefs: 0, filesChanged: 0, version };
  for (const file of await collectCodeFiles(root)) {
    const original = await readFile(file, "utf8");
    const exists = makeResolver(root, path.dirname(file));
    const { text, stamped, html } = stampFile(file, original, version, exists);
    if (html) result.htmlRefs += stamped;
    else result.assetRefs += stamped;
    if (text !== original) {
      await writeFile(file, text, "utf8");
      result.filesChanged += 1;
    }
  }
  return result;
}

async function main() {
  const args = process.argv.slice(2);
  const check = args[0] === "--check";
  const [dir, version] = check ? args.slice(1) : args;
  if (!dir || !version) {
    console.error(`usage: node stamp_index_html.mjs${check ? " --check" : ""} <dir> <version>`);
    process.exit(1);
  }
  if (!VERSION_PATTERN.test(version)) {
    console.error(`invalid asset version: ${JSON.stringify(version)}`);
    process.exit(1);
  }
  const root = path.resolve(dir);
  if (!existsSync(path.join(root, "index.html"))) {
    console.error(`cannot stamp ${root}: index.html is missing`);
    process.exit(1);
  }
  if (check) {
    let changed = 0;
    for (const file of await collectCodeFiles(root)) {
      const original = await readFile(file, "utf8");
      const exists = makeResolver(root, path.dirname(file));
      if (stampFile(file, original, version, exists).text !== original) {
        console.error(`CHECK_FAIL ${path.relative(root, file)} carries references without ?v=${version}`);
        changed += 1;
      }
    }
    if (changed === 0) {
      console.log(`CHECK_OK all local references carry ?v=${version}`);
      return;
    }
    process.exit(2);
  }
  const { htmlRefs, assetRefs, filesChanged } = await stampStaticTree(root, version);
  if (htmlRefs === 0) {
    console.error(`no local asset references found in ${path.join(root, "index.html")}; refusing to stamp`);
    process.exit(1);
  }
  console.log(`STAMPED=${htmlRefs} ASSET_REFS=${assetRefs} FILES=${filesChanged} VERSION=${version} PATH=${root}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
