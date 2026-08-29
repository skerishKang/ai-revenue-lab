import test from 'node:test';
import assert from 'node:assert/strict';
import { PRODUCT_IDENTITY, PRODUCT_ID, PRODUCT_SLUG, ROUTING_MODES } from '../src/index.js';

test('exports the B64 product identity and both routing modes', () => {
  assert.equal(PRODUCT_ID, 'B64');
  assert.equal(PRODUCT_SLUG, 'ai-reward-router');
  assert.deepEqual(PRODUCT_IDENTITY.routingModes, ['TODAY_ROUTE', 'INCOME_PIPELINE']);
  assert.equal(PRODUCT_IDENTITY.initialMarketPriority, 'KOREA_PRIORITY');
  assert.equal(PRODUCT_IDENTITY.supplyScope, 'GLOBAL_BY_DESIGN');
  assert.equal(PRODUCT_IDENTITY.userValueScoreSeparateFromMonetizationScore, true);
  assert.equal(PRODUCT_IDENTITY.walletRequiredForW0, false);
  assert.equal(ROUTING_MODES.TODAY_ROUTE, 'TODAY_ROUTE');
  assert.equal(ROUTING_MODES.INCOME_PIPELINE, 'INCOME_PIPELINE');
});
