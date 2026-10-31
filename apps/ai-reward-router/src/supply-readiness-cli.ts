import { assessAdClickRuntimeConfig } from './ad-click-first/provider-runtime-config.js';
import { assessPublicSupplyFreshness } from './public-supply/domain.js';
import { loadVerifiedPublicOpportunities } from './public-supply/verified-public-opportunities.js';

const assessment = assessAdClickRuntimeConfig(process.env);
const providerStates = Object.values(assessment.providers).map(({provider,mode,readyForServerInitialization,readyForConsumerActivation,missingEnvironmentNames})=>({
  provider,mode,readyForServerInitialization,readyForConsumerActivation,missingEnvironmentNames,
}));
const summary={
  service:'b64-ai-reward-router',
  type:'configuration-readiness-only',
  actualLiveSupplyVerified:false,
  actualRewardPayoutVerified:false,
  providers:providerStates,
  // The curated public lane drops each record 7 days after its source check, so
  // the refresh owner reads the deadline here instead of discovering an empty
  // consumer site afterwards (#987).
  publicSupplyFreshness:assessPublicSupplyFreshness(loadVerifiedPublicOpportunities()),
};
process.stdout.write(JSON.stringify(summary,null,2)+'\n');
