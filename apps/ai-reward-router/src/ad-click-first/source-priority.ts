import type { Source } from '../source-policy/domain.js';

export interface EffectiveSourcePriority {
  readonly sourceId: string;
  readonly registryLaunchPriority: Source['launchPriority'];
  readonly effectiveLaunchPriority: Source['launchPriority'];
  readonly overrideReason: string | null;
}

export const AD_CLICK_FIRST_LAUNCH_PRIORITY_OVERRIDES: Readonly<Record<string, Source['launchPriority']>> = Object.freeze({
  'SRC-AYET': 'P0',
  'SRC-ADPOPCORN': 'P0',
  'SRC-TNK': 'P0',
  'SRC-ADISON': 'P0',
});

export function effectiveSourcePriority(source: Source): EffectiveSourcePriority {
  const override = AD_CLICK_FIRST_LAUNCH_PRIORITY_OVERRIDES[source.sourceId];
  return Object.freeze({
    sourceId: source.sourceId,
    registryLaunchPriority: source.launchPriority,
    effectiveLaunchPriority: override ?? source.launchPriority,
    overrideReason: override
      ? 'OWNER_OVERRIDE_1112_AD_CLICK_FIRST'
      : null,
  });
}
