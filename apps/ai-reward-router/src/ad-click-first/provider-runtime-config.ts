export const PROVIDER_RUNTIME_MODES = ['DISABLED', 'CONFIGURED', 'LIVE_AUTHORIZED'] as const;
export type ProviderRuntimeMode = (typeof PROVIDER_RUNTIME_MODES)[number];

export type ProviderRuntimeId = 'AYET' | 'ADSCEND' | 'TREMENDOUS';

export interface ProviderRuntimeConfigAssessment {
  readonly provider: ProviderRuntimeId;
  readonly mode: ProviderRuntimeMode;
  readonly readyForServerInitialization: boolean;
  readonly readyForConsumerActivation: boolean;
  readonly missingEnvironmentNames: readonly string[];
  readonly secretValuesExposed: false;
}

export interface AdClickRuntimeConfigAssessment {
  readonly providers: Readonly<Record<ProviderRuntimeId, ProviderRuntimeConfigAssessment>>;
  readonly allDisabled: boolean;
  readonly consumerCanBootWithoutProviderAccounts: true;
}

type EnvLike = Readonly<Record<string, string | undefined>>;

interface ProviderRequirement {
  readonly provider: ProviderRuntimeId;
  readonly modeKey: string;
  readonly publicConfigKeys: readonly string[];
  readonly serverSecretKeys: readonly string[];
  readonly ownerAuthorizationKey: string;
}

const REQUIREMENTS: readonly ProviderRequirement[] = Object.freeze([
  Object.freeze({
    provider: 'AYET' as const,
    modeKey: 'B64_AYET_MODE',
    publicConfigKeys: Object.freeze([
      'B64_AYET_PUBLISHER_ID',
      'B64_AYET_PLACEMENT_ID',
      'B64_AYET_REWARDED_ADSLOT_ID',
    ]),
    serverSecretKeys: Object.freeze(['B64_AYET_PUBLISHER_API_KEY']),
    ownerAuthorizationKey: 'B64_AYET_OWNER_AUTHORIZED',
  }),
  Object.freeze({
    provider: 'ADSCEND' as const,
    modeKey: 'B64_ADSCEND_MODE',
    publicConfigKeys: Object.freeze([
      'B64_ADSCEND_PUBLISHER_ID',
      'B64_ADSCEND_OFFERWALL_PROFILE_ID',
    ]),
    serverSecretKeys: Object.freeze(['B64_ADSCEND_API_KEY']),
    ownerAuthorizationKey: 'B64_ADSCEND_OWNER_AUTHORIZED',
  }),
  Object.freeze({
    provider: 'TREMENDOUS' as const,
    modeKey: 'B64_TREMENDOUS_MODE',
    publicConfigKeys: Object.freeze(['B64_TREMENDOUS_CAMPAIGN_ID']),
    serverSecretKeys: Object.freeze(['B64_TREMENDOUS_ACCESS_TOKEN']),
    ownerAuthorizationKey: 'B64_TREMENDOUS_OWNER_AUTHORIZED',
  }),
]);

function nonEmpty(env: EnvLike, key: string): boolean {
  return Boolean(env[key]?.trim());
}

function parseMode(env: EnvLike, key: string): ProviderRuntimeMode {
  const raw = env[key]?.trim() || 'DISABLED';
  if (!PROVIDER_RUNTIME_MODES.includes(raw as ProviderRuntimeMode)) {
    throw new Error(`${key} must be one of ${PROVIDER_RUNTIME_MODES.join(', ')}`);
  }
  return raw as ProviderRuntimeMode;
}

function assessOne(env: EnvLike, requirement: ProviderRequirement): ProviderRuntimeConfigAssessment {
  const mode = parseMode(env, requirement.modeKey);
  if (mode === 'DISABLED') {
    return Object.freeze({
      provider: requirement.provider,
      mode,
      readyForServerInitialization: false,
      readyForConsumerActivation: false,
      missingEnvironmentNames: Object.freeze([]),
      secretValuesExposed: false as const,
    });
  }

  const requiredKeys = [
    ...requirement.publicConfigKeys,
    ...requirement.serverSecretKeys,
  ];
  const missing = requiredKeys.filter((key) => !nonEmpty(env, key));
  const ownerAuthorized = env[requirement.ownerAuthorizationKey]?.trim().toLowerCase() === 'true';
  if (mode === 'LIVE_AUTHORIZED' && !ownerAuthorized) missing.push(requirement.ownerAuthorizationKey);

  return Object.freeze({
    provider: requirement.provider,
    mode,
    readyForServerInitialization: missing.length === 0,
    readyForConsumerActivation: mode === 'LIVE_AUTHORIZED' && missing.length === 0 && ownerAuthorized,
    missingEnvironmentNames: Object.freeze(missing),
    secretValuesExposed: false as const,
  });
}

/**
 * Safe diagnostics only. It never returns credential values, so callers can log the
 * assessment without leaking publisher/API secrets.
 *
 * DISABLED is a valid pre-activation state: the B64 consumer product can boot with
 * zero provider accounts and must simply expose zero real reward cards.
 */
export function assessAdClickRuntimeConfig(env: EnvLike): AdClickRuntimeConfigAssessment {
  const ayet = assessOne(env, REQUIREMENTS[0]!);
  const adscend = assessOne(env, REQUIREMENTS[1]!);
  const tremendous = assessOne(env, REQUIREMENTS[2]!);
  return Object.freeze({
    providers: Object.freeze({ AYET: ayet, ADSCEND: adscend, TREMENDOUS: tremendous }),
    allDisabled: [ayet, adscend, tremendous].every((item) => item.mode === 'DISABLED'),
    consumerCanBootWithoutProviderAccounts: true as const,
  });
}
