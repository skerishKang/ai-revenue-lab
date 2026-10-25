import { assessAdClickRuntimeConfig } from './ad-click-first/provider-runtime-config.js';

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
};
process.stdout.write(JSON.stringify(summary,null,2)+'\n');
