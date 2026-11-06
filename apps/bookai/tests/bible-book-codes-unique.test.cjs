const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const worker = fs.readFileSync(path.join(__dirname, '../public/_worker.js'), 'utf8');
const object = worker.match(/const BIBLE_BOOK_CODES\s*=\s*Object\.freeze\(\{([\s\S]*?)\n\}\);/);
assert.ok(object, 'BIBLE_BOOK_CODES object is present');

const keys = [...object[1].matchAll(/'([^']+)'\s*:/g)].map(match => match[1]);
const seen = new Set();
const duplicates = [];
for (const key of keys) {
  if (seen.has(key)) duplicates.push(key);
  seen.add(key);
}
assert.deepEqual(duplicates, [], 'book-name aliases must not overwrite an earlier object entry');
console.log('PASS: BIBLE_BOOK_CODES has unique keys');
