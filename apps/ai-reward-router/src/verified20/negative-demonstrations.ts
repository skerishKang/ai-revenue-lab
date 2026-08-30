import { OUTLIER_REAL_MATERIAL_CHANGE_CASE } from './outlier-material-change.js';
import {
  CROWDGEN_FIREWEED_STALE_SUPPRESSION,
  ONEFORMA_PODCAST_REJECTED_DUPLICATE,
} from './real-negative-evidence.js';

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

const evidenceById: Readonly<Partial<Record<W8NegativeDemonstrationId, { readonly evidenceRef: string; readonly notes: string }>>> = Object.freeze({
  STALE_SOURCE_SUPPRESSION: Object.freeze({
    evidenceRef: CROWDGEN_FIREWEED_STALE_SUPPRESSION.evidenceId,
    notes: CROWDGEN_FIREWEED_STALE_SUPPRESSION.evidenceSummary,
  }),
  REJECTED_DUPLICATE: Object.freeze({
    evidenceRef: ONEFORMA_PODCAST_REJECTED_DUPLICATE.evidenceId,
    notes: ONEFORMA_PODCAST_REJECTED_DUPLICATE.evidenceSummary,
  }),
  MATERIAL_VERSION_CHANGE: Object.freeze({
    evidenceRef: OUTLIER_REAL_MATERIAL_CHANGE_CASE.evidenceId,
    notes: OUTLIER_REAL_MATERIAL_CHANGE_CASE.evidenceSummary,
  }),
});

/** A negative demonstration becomes PASS only through explicit real evidence. */
export const W8_NEGATIVE_DEMONSTRATIONS: readonly W8NegativeDemonstration[] = Object.freeze(
  W8_NEGATIVE_DEMONSTRATION_IDS.map((id) => {
    const evidence = evidenceById[id];
    return Object.freeze({
      id,
      status: evidence ? 'PASS' as const : 'PENDING' as const,
      evidenceRef: evidence?.evidenceRef ?? null,
      notes: evidence?.notes ?? 'Pending explicit W8 real-evidence demonstration.',
    });
  }),
);

export function w8NegativeGatePassed(items: readonly W8NegativeDemonstration[] = W8_NEGATIVE_DEMONSTRATIONS): boolean {
  return W8_NEGATIVE_DEMONSTRATION_IDS.every((id) => items.some((item) => item.id === id && item.status === 'PASS'));
}
