import test from 'node:test';
import assert from 'node:assert/strict';
import {
  AYET_REWARDED_VIDEO_SDK_URL,
  createAyetPublicClientConfig,
  evaluateAyetWebRewardedVideoGoLive,
} from '../src/ad-click-first/ayet-web-integration.js';

test('ayeT web rewarded video stays blocked until every provider go-live prerequisite exists', () => {
  const result = evaluateAyetWebRewardedVideoGoLive({
    publisherAccountApproved: false,
    placementId: null,
    adslotName: null,
    adsTxtPublished: false,
    cmpConsentFlowReady: false,
    demandSetupFinalized: false,
    publisherApiKeyAvailableServerSide: false,
  });
  assert.equal(result.ready, false);
  assert.equal(result.missing.length, 7);
});

test('ayeT web rewarded video becomes technically ready only when all prerequisites are satisfied', () => {
  const result = evaluateAyetWebRewardedVideoGoLive({
    publisherAccountApproved: true,
    placementId: 123,
    adslotName: 'b64-rewarded-video',
    adsTxtPublished: true,
    cmpConsentFlowReady: true,
    demandSetupFinalized: true,
    publisherApiKeyAvailableServerSide: true,
  });
  assert.equal(result.ready, true);
  assert.deepEqual(result.missing, []);
});

test('public browser config never contains the publisher API key', () => {
  const config = createAyetPublicClientConfig({
    placementId: 123,
    adslotName: 'b64-rewarded-video',
    externalIdentifier: 'user-123',
    optionalParameter: 'p0',
  });
  assert.equal(config.sdkUrl, AYET_REWARDED_VIDEO_SDK_URL);
  assert.equal('publisherApiKey' in config, false);
  assert.equal(config.externalIdentifier, 'user-123');
});

test('public client config rejects malformed placement and user identifiers', () => {
  assert.throws(() => createAyetPublicClientConfig({ placementId: 0, adslotName: 'slot', externalIdentifier: 'user-123' }));
  assert.throws(() => createAyetPublicClientConfig({ placementId: 1, adslotName: '', externalIdentifier: 'user-123' }));
  assert.throws(() => createAyetPublicClientConfig({ placementId: 1, adslotName: 'slot', externalIdentifier: 'x' }));
});
