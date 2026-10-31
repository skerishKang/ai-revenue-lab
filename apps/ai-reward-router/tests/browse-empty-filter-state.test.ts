import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createEmptySupplyConsumerHttpHandler,
  createPublicSupplyConsumerHttpHandler,
} from '../src/http/consumer-http.js';
import { buildAdClickFirstBrowse } from '../src/ad-click-first/consumer-home.js';
import { renderAdClickFirstBrowseWeb } from '../src/ad-click-first/consumer-web.js';

/**
 * #6074, live on workers.dev: `/browse?q=zzzqqq` returned zero cards and the
 * page answered with the supply notice — "아직 확인된 적립이 없습니다 / 검증된
 * 공급자가 연결되면 여기에 바로 표시됩니다". A visitor who typed a word was told
 * B64 has no verified rewards, which is not what happened and is not what the
 * page can know.
 */

const publicSupply = createPublicSupplyConsumerHttpHandler();
const emptySupply = createEmptySupplyConsumerHttpHandler();

async function browse(handler: ReturnType<typeof createPublicSupplyConsumerHttpHandler>, query: string): Promise<string> {
  const response = await handler(new Request(`https://b64.example/browse${query}`));
  assert.equal(response.status, 200);
  return response.text();
}

test('a filter that matches nothing is reported as a filter, not as missing supply', async () => {
  const html = await browse(publicSupply, '?q=zzzqqq');
  assert.match(html, /data-empty-state="NO_FILTER_MATCH"/);
  assert.match(html, /조건에 맞는 기회가 없습니다/);
  assert.doesNotMatch(html, /검증된 공급자가 연결되면/,
    'the supply sentence must not answer a search that simply found nothing');
  assert.doesNotMatch(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/,
    'the browse result area carries one honest status, not two');
});

test('the no-match state gives the visitor the way back out', async () => {
  const html = await browse(publicSupply, '?q=zzzqqq');
  assert.match(html, /<a class="ghost-btn" href="\/browse">전체 기회 보기/);
  assert.match(html, /role="status"/, 'an announced status, not silent emptiness');
});

test('an unfiltered browse with no supply keeps the original honest message', async () => {
  const html = await browse(emptySupply, '');
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.match(html, /아직 확인된 적립이 없습니다/);
  assert.doesNotMatch(html, /NO_FILTER_MATCH/, 'nothing was filtered, so nothing may claim a filter');
});

test('a category or duration condition counts as a filter too', () => {
  const byDuration = renderAdClickFirstBrowseWeb(
    buildAdClickFirstBrowse([], { maxSeconds: 60, publicOpportunities: [] }),
  );
  assert.match(byDuration, /data-empty-state="NO_FILTER_MATCH"/);

  const byCategory = renderAdClickFirstBrowseWeb(
    buildAdClickFirstBrowse([], { category: 'SURVEY', publicOpportunities: [] }),
  );
  assert.match(byCategory, /data-empty-state="NO_FILTER_MATCH"/);

  const plain = renderAdClickFirstBrowseWeb(buildAdClickFirstBrowse([], { publicOpportunities: [] }));
  assert.match(plain, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
});

test('the fix did not touch what real supply looks like', async () => {
  const html = await browse(publicSupply, '');
  assert.match(html, /data-public-card-count="6"/);
  assert.doesNotMatch(html, /NO_FILTER_MATCH/);
  assert.doesNotMatch(html, /지금 바로|즉시 적립|바로 적립 가능/, 'no unapproved lane is advertised as startable');
});
