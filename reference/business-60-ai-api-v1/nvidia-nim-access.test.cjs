'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = __dirname;
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function loadWindow(file) {
  const sandbox = { window: {} };
  vm.runInNewContext(read(file), sandbox);
  return sandbox.window;
}

test('NVIDIA NIM is a verified persistent developer-prototyping opportunity', () => {
  const signals = Array.from(loadWindow('data/access-signals.js').B60_ACCESS_SIGNALS);
  const nim = signals.find(item => item.id === 'nvidia-nim-dev-free');

  assert.ok(nim);
  assert.equal(nim.provider, 'NVIDIA');
  assert.equal(nim.dealType, 'PERMANENT_FREE');
  assert.equal(nim.verification, 'VERIFIED_OFFICIAL_WEB');
  assert.equal(nim.verifiedAt, '2026-08-25');
  assert.equal(nim.freeLabel, 'Free prototyping');
  assert.match(nim.summary, /up to 16 GPUs/);
  assert.match(nim.facts.join(' '), /Production use has separate/);
  assert.ok(nim.sources.some(source => source.url === 'https://docs.api.nvidia.com/nim/docs/run-anywhere'));
  assert.ok(nim.sources.some(source => source.url === 'https://developer.nvidia.com/nim'));
  assert.ok(nim.sources.some(source => source.url === 'https://www.nvidia.com/en-us/ai-data-science/products/nim-microservices/'));
});

test('NVIDIA NIM has raster editorial context rather than SVG or generated filler', () => {
  const media = loadWindow('data/editorial-media.js').B60_EDITORIAL_MEDIA;
  const nimMedia = media['nvidia-nim-dev-free'];

  assert.ok(nimMedia);
  assert.match(nimMedia.image, /\.webp$/);
  assert.doesNotMatch(nimMedia.image, /\.svg$/i);
  assert.match(nimMedia.source, /Unsplash/);
  assert.match(nimMedia.alt, /서버 랙|데이터센터/);
});
