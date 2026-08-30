import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('owner activation runbook exists and keeps all live providers disabled by default', async () => {
  const text = await readFile('OWNER_ACTIVATION_RUNBOOK.md', 'utf8');
  assert.equal(text.includes('B64_AYET_MODE=DISABLED'), true);
  assert.equal(text.includes('B64_ADSCEND_MODE=DISABLED'), true);
  assert.equal(text.includes('B64_TREMENDOUS_MODE=DISABLED'), true);
});

test('owner activation runbook keeps secrets server-side and requires explicit owner authorization', async () => {
  const text = await readFile('OWNER_ACTIVATION_RUNBOOK.md', 'utf8');
  assert.equal(text.includes('Never commit real provider IDs, API keys, access tokens'), true);
  assert.equal(text.includes('B64_AYET_OWNER_AUTHORIZED=true'), true);
  assert.equal(text.includes('B64_ADSCEND_OWNER_AUTHORIZED=true'), true);
  assert.equal(text.includes('B64_TREMENDOUS_OWNER_AUTHORIZED=true'), true);
  assert.equal(text.includes('If any condition becomes unknown, disable the provider rather than guessing.'), true);
});

test('owner activation runbook never treats configuration alone as live authorization', async () => {
  const text = await readFile('OWNER_ACTIVATION_RUNBOOK.md', 'utf8');
  assert.equal(text.includes('Do not use `LIVE_AUTHORIZED` merely because the fields are populated.'), true);
  assert.equal(text.includes('Provider account approval alone does not authorize every offer.'), true);
  assert.equal(text.includes('No external reward order may originate from a provisional or reversed ad event.'), true);
});
