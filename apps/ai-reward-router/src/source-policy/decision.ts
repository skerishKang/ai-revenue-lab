import {
  ACQUISITION_MODES,
  type EffectiveAcquisitionDecision,
  type EffectiveAcquisitionInput,
  type SourceCollectionGate,
} from './domain.js';

const isUnpassed = (gate: SourceCollectionGate): boolean =>
  gate.required && gate.status !== 'PASS' && gate.status !== 'WAIVED';

const supportsManualBehavior = (mode: EffectiveAcquisitionInput['source']['acquisitionMode']): boolean =>
  mode === ACQUISITION_MODES.MANUAL_CURATED_OFFICIAL_SOURCE ||
  mode === ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY;

const supportsAutomatedBehavior = (mode: EffectiveAcquisitionInput['source']['acquisitionMode']): boolean =>
  mode === ACQUISITION_MODES.PARTNER_API ||
  mode === ACQUISITION_MODES.PARTNER_FEED ||
  mode === ACQUISITION_MODES.PARTNER_WIDGET_SDK ||
  mode === ACQUISITION_MODES.PUBLIC_WEB_ALLOWED;

/**
 * Pure W1 gate. It decides permission for an attempted behavior; it never
 * fetches a source, creates credentials, verifies an opportunity, or publishes data.
 */
export function effectiveAcquisitionDecision(
  input: EffectiveAcquisitionInput,
): EffectiveAcquisitionDecision {
  const { source, policy, gates, attempt } = input;

  if (attempt === 'SHADOW' || source.lane === 'SHADOW_ONLY' || source.acquisitionMode === ACQUISITION_MODES.SHADOW_ONLY) {
    return 'SHADOW_ONLY';
  }

  if (source.lane === 'HOLD' || source.lane === 'REJECT') {
    return 'BLOCK';
  }

  if (attempt === 'MANUAL_CURATED' || attempt === 'DIRECTORY') {
    if (!supportsManualBehavior(source.acquisitionMode)) return 'BLOCK';
    // W1/W4A contract: PENDING/UNKNOWN is not permission. Manual/deep-link
    // curation may proceed only after an explicit PASS or PASS_WITH_LIMITS.
    if (policy.decision !== 'PASS' && policy.decision !== 'PASS_WITH_LIMITS') return 'BLOCK';
    if (policy.decision === 'PASS_WITH_LIMITS' && input.limitsSatisfied !== true) return 'BLOCK';
    return 'MANUAL_ONLY';
  }

  if (!supportsAutomatedBehavior(source.acquisitionMode)) return 'BLOCK';
  if (policy.decision === 'PENDING' || policy.decision === 'BLOCK') return 'BLOCK';
  if (policy.decision === 'PASS_WITH_LIMITS' && input.limitsSatisfied !== true) return 'BLOCK';
  if (policy.automationPermission !== 'ALLOWED' && policy.automationPermission !== 'LIMITED') return 'BLOCK';
  if (source.acquisitionMode !== ACQUISITION_MODES.PUBLIC_WEB_ALLOWED && input.credentialsAvailable !== true) return 'BLOCK';

  const unpassedBlockGate = gates.some((gate) => isUnpassed(gate) && gate.failureAction === 'BLOCK');
  if (unpassedBlockGate) return 'BLOCK';

  const unpassedShadowGate = gates.some((gate) => isUnpassed(gate) && gate.failureAction === 'SHADOW');
  if (unpassedShadowGate) return 'SHADOW_ONLY';

  return 'AUTOMATED_ALLOWED';
}
