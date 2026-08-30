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

/**
 * Real public CrowdGen Experts page observed 2026-08-30 contains unresolved
 * template/semantic conflicts: lorem-ipsum placeholder copy, duplicate
 * PROJECT ARISTOTLE cards with incompatible descriptions, and project labels
 * that cannot be treated as reliable current inventory without human review.
 */
export const CROWDGEN_EXPERTS_LOW_CONFIDENCE_REVIEW: W8RealNegativeEvidenceCase = Object.freeze({
  evidenceId: 'w8-real-negative-crowdgen-experts-low-confidence-20260830',
  demonstrationId: 'LOW_CONFIDENCE_REVIEW',
  sourceId: 'SRC-CROWDGEN',
  canonicalUrl: 'https://crowdgen.com/experts/',
  observedAt: '2026-08-30T09:27:00.000Z',
  realEvidence: true,
  disposition: 'REVIEW_REQUIRED',
  countableVerified20: false,
  reasonCodes: Object.freeze([
    'PLACEHOLDER_LOREM_IPSUM_PRESENT',
    'DUPLICATE_PROJECT_NAME_WITH_CONFLICTING_DESCRIPTION',
    'PROJECT_CARD_SEMANTICS_NOT_RELIABLE_CURRENT_INVENTORY',
    'HUMAN_REVIEW_REQUIRED_BEFORE_NORMALIZATION',
  ]),
  evidenceSummary: 'CrowdGen Experts currently renders placeholder lorem-ipsum descriptions and repeats PROJECT ARISTOTLE with materially inconsistent task descriptions. B64 therefore routes this source observation to LOW_CONFIDENCE review and does not normalize any of those cards into VERIFIED 20.',
});

/**
 * Real official PanelPower detail route observed 2026-08-30. The provider
 * renders an application-level terminal page stating that the focus group is
 * closed or cannot be found. A search-discovered detail route with that state
 * must be suppressed rather than surfaced as a live earning opportunity.
 */
export const PANELPOWER_ENDED_DETAIL_BROKEN_LINK: W8RealNegativeEvidenceCase = Object.freeze({
  evidenceId: 'w8-real-negative-panelpower-ended-detail-7381-20260830',
  demonstrationId: 'BROKEN_LINK_SUPPRESSION',
  sourceId: 'SRC-PANELPOWER',
  canonicalUrl: 'https://www.panel.co.kr/survey/panel/detail/7381',
  observedAt: '2026-08-30T10:24:00.000Z',
  realEvidence: true,
  disposition: 'SUPPRESSED',
  countableVerified20: false,
  reasonCodes: Object.freeze([
    'OFFICIAL_DETAIL_ROUTE_TERMINAL_STATE',
    'PROVIDER_SAYS_RECRUITMENT_CLOSED_OR_NOT_FOUND',
    'NOT_LIVE_CURRENT_SUPPLY',
    'SUPPRESS_FROM_RECOMMENDATION_AND_VERIFIED_LEDGER',
  ]),
  evidenceSummary: 'An official PanelPower survey detail route currently resolves to the provider message that the focus group recruitment is closed or the item cannot be found. B64 treats this terminal/missing detail as broken-for-live-supply and suppresses it instead of presenting it as current earning inventory.',
});
