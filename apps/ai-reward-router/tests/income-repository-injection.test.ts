import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { createTestAuthResolver } from '../src/income-pipeline/auth.js';
import type { UserIncomeRecord } from '../src/income-pipeline/domain.js';
import type { UserIncomeRepository } from '../src/income-pipeline/store.js';

test('pipeline accepts server-injected async repository rather than process singleton', async () => {
  const records = new Map<string, UserIncomeRecord[]>();
  const calls: string[] = [];
  const repo: UserIncomeRepository = {
    async getByUser(userId) { calls.push('get:' + userId); return records.get(userId) ?? []; },
    async save(record) { calls.push('save:' + record.userId); records.set(record.userId, [...(records.get(record.userId) ?? []).filter(r => r.id !== record.id), record]); },
    async delete(userId, id) { calls.push('delete:' + userId); const before = records.get(userId) ?? []; records.set(userId, before.filter(r => r.id !== id)); return before.length !== records.get(userId)!.length; },
  };
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createTestAuthResolver('verified-subject'),
    incomeRepository: repo,
  });
  const response = await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Injected+repo&vendor=Test&status=SAVED',
  }));
  assert.equal(response.status, 303);
  const page = await handler(new Request('https://b64.example/pipeline'));
  assert.match(await page.text(), /Injected repo/);
  assert.deepEqual(calls, ['get:verified-subject', 'save:verified-subject', 'get:verified-subject']);
});
