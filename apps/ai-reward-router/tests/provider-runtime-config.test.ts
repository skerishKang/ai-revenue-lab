import test from 'node:test';
import assert from 'node:assert/strict';
import { assessAdClickRuntimeConfig } from '../src/ad-click-first/provider-runtime-config.js';

test('zero provider accounts is a valid pre-activation boot state', () => {
  const assessment = assessAdClickRuntimeConfig({});
  assert.equal(assessment.allDisabled, true);
  assert.equal(assessment.consumerCanBootWithoutProviderAccounts, true);
  assert.equal(assessment.providers.AYET.readyForConsumerActivation, false);
  assert.equal(assessment.providers.ADSCEND.readyForConsumerActivation, false);
  assert.equal(assessment.providers.TREMENDOUS.readyForConsumerActivation, false);
  assert.deepEqual(assessment.providers.AYET.missingEnvironmentNames, []);
});

test('CONFIGURED mode reports missing field names without exposing secret values', () => {
  const assessment = assessAdClickRuntimeConfig({
    B64_AYET_MODE: 'CONFIGURED',
    B64_AYET_PUBLISHER_ID: 'publisher-123',
    B64_AYET_PUBLISHER_API_KEY: 'super-secret-key',
  });
  assert.equal(assessment.providers.AYET.readyForServerInitialization, false);
  assert.equal(assessment.providers.AYET.secretValuesExposed, false);
  assert.deepEqual(assessment.providers.AYET.missingEnvironmentNames, [
    'B64_AYET_PLACEMENT_ID',
    'B64_AYET_REWARDED_ADSLOT_ID',
  ]);
  assert.equal(JSON.stringify(assessment).includes('super-secret-key'), false);
});

test('LIVE_AUTHORIZED mode cannot activate without explicit owner authorization', () => {
  const assessment = assessAdClickRuntimeConfig({
    B64_ADSCEND_MODE: 'LIVE_AUTHORIZED',
    B64_ADSCEND_PUBLISHER_ID: 'publisher',
    B64_ADSCEND_OFFERWALL_PROFILE_ID: 'profile',
    B64_ADSCEND_API_KEY: 'secret',
    B64_ADSCEND_OWNER_AUTHORIZED: 'false',
  });
  assert.equal(assessment.providers.ADSCEND.readyForServerInitialization, false);
  assert.equal(assessment.providers.ADSCEND.readyForConsumerActivation, false);
  assert.deepEqual(assessment.providers.ADSCEND.missingEnvironmentNames, [
    'B64_ADSCEND_OWNER_AUTHORIZED',
  ]);
});

test('LIVE_AUTHORIZED becomes config-ready only when required config and owner authority exist', () => {
  const assessment = assessAdClickRuntimeConfig({
    B64_TREMENDOUS_MODE: 'LIVE_AUTHORIZED',
    B64_TREMENDOUS_CAMPAIGN_ID: 'campaign',
    B64_TREMENDOUS_ACCESS_TOKEN: 'secret',
    B64_TREMENDOUS_OWNER_AUTHORIZED: 'true',
  });
  assert.equal(assessment.providers.TREMENDOUS.readyForServerInitialization, true);
  assert.equal(assessment.providers.TREMENDOUS.readyForConsumerActivation, true);
  assert.equal(assessment.providers.TREMENDOUS.secretValuesExposed, false);
});

test('invalid runtime mode fails closed', () => {
  assert.throws(
    () => assessAdClickRuntimeConfig({ B64_AYET_MODE: 'AUTO_ENABLE' }),
    /B64_AYET_MODE must be one of/,
  );
});
