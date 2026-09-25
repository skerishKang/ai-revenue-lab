/**
 * CLAW4 #3083 — Desktop shell device lifecycle PRESENTATION states.
 *
 * Authority boundary (see issue #3083 and the accepted #3074 CLAW4 audit):
 *
 *   PRESENTATION_STATE_ONLY=YES
 *   CANONICAL_DEVICE_TRUTH_OWNED_BY=#3080_broker_pairing_and_server_projection
 *   RENDERER_MAY_FORGE_ONLINE=NO
 *
 * The renderer never constructs these values on its own. It only receives a
 * projection produced by the Electron main process, and even the main process
 * may only derive ONLINE from a runner-health / server-projection fact, never
 * from a renderer-supplied claim.
 */

export const DEVICE_LIFECYCLE_STATES = [
  'NOT_PAIRED',
  'PAIRING',
  'OFFLINE',
  'ONLINE',
  'ACTION_REQUIRED',
] as const;

export type DeviceLifecycleState = (typeof DEVICE_LIFECYCLE_STATES)[number];

export const DEVICE_LIFECYCLE = Object.freeze({
  PRESENTATION_STATE_ONLY: true,
  CANONICAL_TRUTH_OWNED_BY: '#3080',
  RENDERER_MAY_FORGE_ONLINE: false,
  STATES: DEVICE_LIFECYCLE_STATES,
} as const);

/**
 * Allowed presentation transitions.
 *
 * ONLINE may only be entered from a state that already represents a reachable
 * runner, and it may never be entered by a direct renderer request: the only
 * inbound edge to ONLINE is `supervision` (a main-process health fact).
 */
export const DEVICE_LIFECYCLE_TRANSITIONS: Readonly<
  Record<DeviceLifecycleState, readonly DeviceLifecycleState[]>
> = Object.freeze({
  NOT_PAIRED: ['PAIRING'],
  PAIRING: ['ONLINE', 'OFFLINE', 'NOT_PAIRED', 'ACTION_REQUIRED'],
  OFFLINE: ['PAIRING', 'ONLINE', 'ACTION_REQUIRED', 'NOT_PAIRED'],
  ONLINE: ['OFFLINE', 'ACTION_REQUIRED'],
  ACTION_REQUIRED: ['PAIRING', 'OFFLINE', 'ONLINE'],
});

export type DeviceLifecycleTrigger =
  | 'user_pairing_request'
  | 'pairing_seam_accepted'
  | 'pairing_seam_rejected'
  | 'supervision'
  | 'runner_unhealthy'
  | 'server_projection'
  | 'session_lost';

export interface DeviceLifecycleProjection {
  readonly state: DeviceLifecycleState;
  readonly sinceRevision: number;
  readonly reason: string;
  /** True only when `state` was derived from an actual runner/server fact. */
  readonly evidenceBacked: boolean;
}

export class DeviceLifecycleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DeviceLifecycleError';
  }
}

export function canTransition(
  from: DeviceLifecycleState,
  to: DeviceLifecycleState,
): boolean {
  return DEVICE_LIFECYCLE_TRANSITIONS[from].includes(to);
}

/**
 * Deterministic, renderer-independent projection reducer.
 *
 * Fail-closed rule: an unknown `to` state, or an unlisted edge, is rejected —
 * it is never silently coerced into a "healthier" state.
 */
export function projectDeviceLifecycle(
  current: DeviceLifecycleProjection,
  trigger: DeviceLifecycleTrigger,
  to: DeviceLifecycleState,
  reason: string,
): DeviceLifecycleProjection {
  if (!DEVICE_LIFECYCLE_STATES.includes(to)) {
    throw new DeviceLifecycleError(`unknown device lifecycle state: ${String(to)}`);
  }
  if (!canTransition(current.state, to)) {
    throw new DeviceLifecycleError(
      `illegal device lifecycle transition: ${current.state} -> ${to}`,
    );
  }
  if (to === 'ONLINE' && trigger !== 'supervision' && trigger !== 'server_projection') {
    throw new DeviceLifecycleError(
      'ONLINE requires a supervision or server_projection fact; renderer claims are not evidence',
    );
  }
  return Object.freeze({
    state: to,
    sinceRevision: current.sinceRevision + 1,
    reason,
    evidenceBacked: trigger === 'supervision' || trigger === 'server_projection',
  });
}

export function initialDeviceLifecycleProjection(): DeviceLifecycleProjection {
  return Object.freeze({
    state: 'NOT_PAIRED',
    sinceRevision: 0,
    reason: 'shell initialised without a canonical pairing projection',
    evidenceBacked: false,
  });
}

export const SHELL_EVIDENCE = Object.freeze({
  ELECTRON_REACT_SHELL: true,
  HEADLESS_RUNNER_SEPARATE: true,
  CONTEXT_ISOLATION: true,
  NARROW_TYPED_IPC: true,
  RENDERER_EXECUTION_AUTHORITY: false,
  RUNNER_SUPERVISION: true,
  PAIRING_DEEPLINK_SEAM: true,
  WINDOWS_PACKAGE_SOURCE_READY: true,
  PRODUCTION_SIGNING: false,
  SECOND_EXECUTION_AUTHORITY: 0,
  SECOND_PAIRING_AUTHORITY: 0,
} as const);
