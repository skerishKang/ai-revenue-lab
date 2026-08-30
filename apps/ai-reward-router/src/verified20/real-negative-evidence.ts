export interface W8RealNegativeEvidenceCase {
  readonly evidenceId: string;
  readonly demonstrationId: 'BROKEN_LINK_SUPPRESSION' | 'STALE_SOURCE_SUPPRESSION' | 'REJECTED_DUPLICATE' | 'LOW_CONFIDENCE_REVIEW' | 'MATERIAL_VERSION_CHANGE';
  readonly sourceId: string;
  readonly canonicalUrl: string;
  readonly observedAt: string;
  readonly realEvidence: true;
  readonly disposition: 'SUPPRESSED' | 'REJECTED' | 'REVIEW_REQUIRED' | 'NEW_VERSION_REVIEW_REQUIRED';
  readonly countableVerified20: false;
  readonly reasonCodes: readonly string[];
  readonly evidenceSummary: string;
}

/**
 * Real public CrowdGen page observed 2026-08-30. The page still contains an
 * expired “double pay until 15 October 2024” promotion while also presenting a
 * normal hourly rate. That time-conflicted source must not silently enter the
 * VERIFIED-20 ledger as current truth.
 */
export const CROWDGEN_FIREWEED_STALE_SUPPRESSION: W8RealNegativeEvidenceCase = Object.freeze({
  evidenceId: 'w8-real-negative-crowdgen-fireweed-stale-20260830',
  demonstrationId: 'STALE_SOURCE_SUPPRESSION',
  sourceId: 'SRC-CROWDGEN',
  canonicalUrl: 'https://crowdgen.com/fireweed-korean-remote/',
  observedAt: '2026-08-30T08:55:00.000Z',
  realEvidence: true,
  disposition: 'SUPPRESSED',
  countableVerified20: false,
  reasonCodes: Object.freeze([
    'EXPIRED_PROMOTION_STILL_RENDERED',
    'TIME_CONFLICT_IN_PUBLIC_COMPENSATION_CONTEXT',
    'FRESHNESS_REVIEW_REQUIRED_BEFORE_COUNTING',
  ]),
  evidenceSummary: 'Observed public page contains an expired double-pay promotion ending 2024-10-15 while the page is still reachable in 2026. B64 suppresses the candidate from VERIFIED 20 rather than treating the stale promotion context as current.',
});

/**
 * Real duplicate discovery observed on OneForma: the current public projects
 * directory and the direct project detail both expose the same Multilingual
 * Podcast Transcription And Speech Annotator project. These are two discovery
 * paths to one canonical opportunity, not two earning opportunities.
 */
export const ONEFORMA_PODCAST_REJECTED_DUPLICATE: W8RealNegativeEvidenceCase = Object.freeze({
  evidenceId: 'w8-real-negative-oneforma-podcast-duplicate-20260830',
  demonstrationId: 'REJECTED_DUPLICATE',
  sourceId: 'SRC-ONEFORMA',
  canonicalUrl: 'https://www.oneforma.com/projects/multilingual-podcast-transcription-and-speech-annotator/',
  observedAt: '2026-08-30T09:21:00.000Z',
  realEvidence: true,
  disposition: 'REJECTED',
  countableVerified20: false,
  reasonCodes: Object.freeze([
    'DIRECTORY_AND_DETAIL_SAME_PROJECT',
    'SAME_CANONICAL_URL',
    'SAME_PROVIDER_EXTERNAL_IDENTITY',
    'SECOND_DISCOVERY_DOES_NOT_CREATE_NEW_SLOT',
  ]),
  evidenceSummary: 'The live OneForma projects directory lists Multilingual Podcast Transcription And Speech Annotator and links to the same direct project detail already represented by slot 10. B64 canonicalizes both observations to one opportunity identity and rejects the second discovery as a duplicate instead of inflating VERIFIED 20.',
});
