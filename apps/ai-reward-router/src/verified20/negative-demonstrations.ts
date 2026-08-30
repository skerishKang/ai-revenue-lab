export const W8_NEGATIVE_DEMONSTRATION_IDS = [
  'BROKEN_LINK_SUPPRESSION',
  'STALE_SOURCE_SUPPRESSION',
  'REJECTED_DUPLICATE',
  'LOW_CONFIDENCE_REVIEW',
  'MATERIAL_VERSION_CHANGE',
] as const;

export type W8NegativeDemonstrationId = (typeof W8_NEGATIVE_DEMONSTRATION_IDS)[number];
export type W8NegativeDemonstrationStatus = 'PENDING' | 'PASS';

export interface W8NegativeDemonstration {
  readonly id: W8NegativeDemonstrationId;
  readonly status: W8NegativeDemonstrationStatus;
  readonly evidenceRef: string | null;
  readonly notes: string;
}

/**
 * None of these are allowed to become PASS merely because equivalent synthetic
 * unit tests exist. W8 requires explicit evidence in the real VERIFIED-20 gate.
 */
export const W8_NEGATIVE_DEMONSTRATIONS: readonly W8NegativeDemonstration[] = Object.freeze(
  W8_NEGATIVE_DEMONSTRATION_IDS.map((id) => Object.freeze({
    id,
    status: 'PENDING' as const,
    evidenceRef: null,
    notes: 'Pending explicit W8 real-evidence demonstration.',
  })),
);

export function w8NegativeGatePassed(items: readonly W8NegativeDemonstration[] = W8_NEGATIVE_DEMONSTRATIONS): boolean {
  return W8_NEGATIVE_DEMONSTRATION_IDS.every((id) => items.some((item) => item.id === id && item.status === 'PASS'));
}
