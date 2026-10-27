import test from 'node:test';
import assert from 'node:assert/strict';
import { buildUserIncomeSummary, type UserIncomeRecord } from '../src/income-pipeline/domain.js';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { createTestAuthResolver } from '../src/income-pipeline/auth.js';
import { InMemoryUserIncomeRepository } from '../src/income-pipeline/store.js';

const USER = 'usr_payout_honesty_0001';

function incomeRecord(overrides: Partial<UserIncomeRecord>): UserIncomeRecord {
  return {
    id: 'rec-completed',
    userId: USER,
    opportunityId: null,
    externalRef: null,
    sourceType: 'MANUAL',
    title: 'Prolific 리서치',
    vendor: 'Prolific',
    status: 'COMPLETED',
    expectedAmount: 9_000,
    expectedCurrency: 'KRW',
    actualAmount: 12_000,
    actualCurrency: 'KRW',
    appliedAt: null,
    acceptedAt: null,
    completedAt: '2026-10-20T00:00:00.000Z',
    paidAt: null,
    expiresAt: null,
    note: null,
    sourceUrl: null,
    createdAt: '2026-10-20T00:00:00.000Z',
    updatedAt: '2026-10-20T00:00:00.000Z',
    ...overrides,
  };
}

test('unpaid records do not enter the realised-income total', () => {
  const summary = buildUserIncomeSummary([
    incomeRecord({}),
    incomeRecord({ id: 'rec-paid', status: 'PAID', paidAt: '2026-10-26T00:00:00.000Z', actualAmount: 3_000 }),
  ]);

  assert.equal(summary.completedCount, 2);
  assert.equal(summary.paidCount, 1);
  assert.equal(summary.expectedTotal.get('KRW'), 18_000, 'expected income still covers every record');
  assert.equal(
    summary.actualTotal.get('KRW'),
    3_000,
    'the realised total must only sum confirmed PAID records',
  );
});

test('non-PAID records never build a paid-out total', () => {
  const summary = buildUserIncomeSummary([incomeRecord({})]);
  assert.equal(summary.actualTotal.size, 0);
});

async function renderPipeline(records: readonly UserIncomeRecord[]): Promise<string> {
  const repository = new InMemoryUserIncomeRepository();
  for (const record of records) await repository.save(record);
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createTestAuthResolver(USER),
    incomeRepository: repository,
  });
  const response = await handler(new Request('https://b64.example/pipeline'));
  assert.equal(response.status, 200);
  return response.text();
}

test('a completed record is shown as payout-unconfirmed', async () => {
  const html = await renderPipeline([incomeRecord({})]);
  assert.match(html, /summary-value--actual">0</);
  assert.ok(html.includes('지급 확인 전'), 'an unpaid amount never carries a realised payout figure');
  assert.ok(!html.includes('12,000 KRW'), 'an unconfirmed payout must not render as realised income');
  assert.ok(html.includes('9,000 KRW'), 'the expected amount stays visible');
});

test('only a PAID record shows a realised payout amount', async () => {
  const html = await renderPipeline([
    incomeRecord({ id: 'rec-paid', status: 'PAID', paidAt: '2026-10-26T00:00:00.000Z', actualAmount: 3_000 }),
  ]);
  assert.match(html, /summary-value--actual">3,000 KRW</);
  assert.ok(html.includes('지급 완료'));
});
