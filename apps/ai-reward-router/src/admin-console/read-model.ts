import type {
  EarningOpportunity,
  OpportunityVersion,
} from '../persistence/domain.js';
import type { SourceLane } from '../source-policy/domain.js';
import {
  TRUST_STATUS_LABELS,
  type AdminConsoleState,
  type AdminRoute,
} from './domain.js';

const LANE_ORDER: readonly SourceLane[] = ['BUILD', 'SHADOW_ONLY', 'NEGOTIATE', 'INVENTORY_TEST', 'HOLD', 'REJECT'];

function byId<T extends { readonly id: string }>(items: readonly T[], id: string): T | null {
  return items.find((item) => item.id === id) ?? null;
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function displayUnknown(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'NULL / UNKNOWN';
  if (Array.isArray(value)) return value.length === 0 ? '[]' : value.map((item) => displayUnknown(item)).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function currentDisplayVersion(state: AdminConsoleState, opportunity: EarningOpportunity): OpportunityVersion | null {
  if (opportunity.currentVersionId !== null) return byId(state.versions, opportunity.currentVersionId);
  return state.versions
    .filter((version) => version.offerId === opportunity.id)
    .sort((a, b) => b.versionNumber - a.versionNumber)[0] ?? null;
}

export function buildDashboard(state: AdminConsoleState) {
  const sourcesByLane = Object.fromEntries(
    LANE_ORDER.map((lane) => [lane, state.sources.filter((source) => source.lane === lane).length]),
  ) as Record<SourceLane, number>;
  const openQueue = state.reviewQueue.filter((item) => item.state !== 'RESOLVED');
  const openVersionIds = new Set(openQueue.map((item) => item.offerVersionId));
  const materialChangesAwaitingApproval = state.changes.filter(
    (change) => change.material && openVersionIds.has(change.newVersionId),
  ).length;
  const categoryCounts = new Map<string, number>();
  const ladderCounts = new Map<string, number>();
  for (const opportunity of state.opportunities) {
    const version = currentDisplayVersion(state, opportunity);
    if (!version) continue;
    categoryCounts.set(version.opportunityCategory, (categoryCounts.get(version.opportunityCategory) ?? 0) + 1);
    ladderCounts.set(version.incomeLadderLevel, (ladderCounts.get(version.incomeLadderLevel) ?? 0) + 1);
  }
  return Object.freeze({
    sourcesByLane: Object.freeze(sourcesByLane),
    verifiedOpportunities: state.versions.filter((item) => item.verificationState === 'VERIFIED').length,
    reviewQueueCount: openQueue.length,
    staleBrokenCount: state.staleBroken.filter((item) => item.state !== 'RESOLVED').length,
    materialChangesAwaitingApproval,
    categoryCounts: Object.freeze(Object.fromEntries([...categoryCounts.entries()].sort())),
    ladderCounts: Object.freeze(Object.fromEntries([...ladderCounts.entries()].sort())),
  });
}

export function buildSourceRows(state: AdminConsoleState) {
  return Object.freeze(state.sources.map((source) => {
    const policy = state.policies.find((item) => item.sourceId === source.sourceId) ?? null;
    const gates = state.gates.filter((item) => item.sourceId === source.sourceId);
    return Object.freeze({
      sourceId: source.sourceId,
      name: source.sourceName,
      sourceType: source.sourceType,
      lane: source.lane,
      acquisitionMode: source.acquisitionMode,
      verificationState: source.verificationState,
      policyDecision: policy?.decision ?? 'PENDING',
      riskTier: source.riskTier,
      updateCadence: source.updateCadence,
      gatePassCount: gates.filter((gate) => gate.status === 'PASS' || gate.status === 'WAIVED').length,
      gateRequiredCount: gates.filter((gate) => gate.required).length,
      nextAction: source.nextAction,
    });
  }));
}

export function buildOpportunityRows(state: AdminConsoleState) {
  return Object.freeze(state.opportunities.map((opportunity) => {
    const version = currentDisplayVersion(state, opportunity);
    return Object.freeze({
      offerId: opportunity.id,
      sourceId: opportunity.sourceId,
      title: version?.title ?? 'NULL / UNKNOWN',
      opportunityCategory: version?.opportunityCategory ?? 'NULL / UNKNOWN',
      incomeLadderLevel: version?.incomeLadderLevel ?? 'NULL / UNKNOWN',
      compensationType: version?.compensationType ?? 'NULL / UNKNOWN',
      advertisedCompensationValue: version?.advertisedCompensationValue ?? null,
      expectedPayoutValue: version?.expectedPayoutValue ?? null,
      compensationCurrency: version?.compensationCurrency ?? null,
      applicationRequired: version?.applicationRequired ?? null,
      qualificationRequired: version?.qualificationRequired ?? null,
      repeatability: version?.repeatability ?? null,
      supplyAvailabilityState: version?.supplyAvailabilityState ?? null,
      verificationState: version?.verificationState ?? 'UNVERIFIED',
      lifecycleState: opportunity.lifecycleState,
      versionId: version?.id ?? null,
      versionNumber: version?.versionNumber ?? null,
    });
  }));
}

export function buildOpportunityReview(state: AdminConsoleState, versionId: string) {
  const version = byId(state.versions, versionId);
  if (!version) throw new Error(`Unknown opportunity version: ${versionId}`);
  const opportunity = byId(state.opportunities, version.offerId);
  if (!opportunity) throw new Error(`Missing opportunity for version: ${versionId}`);
  const snapshot = byId(state.snapshots, version.sourceSnapshotId);
  const evidence = state.evidence.filter((item) => item.offerVersionId === version.id);
  const review = state.reviewQueue.find((item) => item.offerVersionId === version.id && item.state !== 'RESOLVED') ?? null;
  const change = state.changes.find((item) => item.newVersionId === version.id) ?? null;
  const previousVersion = change ? byId(state.versions, change.previousVersionId) : null;
  return Object.freeze({ version, opportunity, snapshot, evidence: Object.freeze(evidence), review, change, previousVersion });
}

function nav(): string {
  return `<nav>${[
    ['DASHBOARD', 'Dashboard'],
    ['SOURCES', 'Sources'],
    ['OPPORTUNITIES', 'Earning Opportunities'],
    ['REVIEW_QUEUE', 'Review Queue'],
    ['OPPORTUNITY_REVIEW', 'Opportunity Review'],
    ['CHANGES', 'Changes'],
    ['STALE_BROKEN', 'Stale / Broken'],
    ['AUDIT_LOG', 'Audit Log'],
  ].map(([route, label]) => `<a href="?route=${route}">${label}</a>`).join(' · ')}</nav>`;
}

function table(headers: readonly string[], rows: readonly (readonly unknown[])[]): string {
  return `<table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(displayUnknown(cell))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

export function renderAdminRoute(state: AdminConsoleState, route: AdminRoute, selectedId?: string): string {
  const statusLegend = `<section><h2>Trust states are separate</h2><p>${TRUST_STATUS_LABELS.map(escapeHtml).join(' · ')}</p></section>`;
  let body = '';
  if (route === 'DASHBOARD') {
    const dashboard = buildDashboard(state);
    body = `<h1>B64 Admin Console</h1><p>Generalized earning-opportunity operations</p>${table(
      ['Metric', 'Value'],
      [
        ['Review queue', dashboard.reviewQueueCount],
        ['Material changes awaiting approval', dashboard.materialChangesAwaitingApproval],
        ['Stale / broken', dashboard.staleBrokenCount],
        ['Verified versions', dashboard.verifiedOpportunities],
      ],
    )}${table(['Source lane', 'Count'], Object.entries(dashboard.sourcesByLane))}`;
  } else if (route === 'SOURCES') {
    const rows = buildSourceRows(state);
    body = `<h1>Sources</h1><p>Product lane is distinct from acquisition permission/policy state.</p>${table(
      ['Source', 'Type', 'Lane', 'Acquisition Mode', 'Policy', 'Verification', 'Risk', 'Next Action'],
      rows.map((row) => [row.name, row.sourceType, row.lane, row.acquisitionMode, row.policyDecision, row.verificationState, row.riskTier, row.nextAction]),
    )}`;
  } else if (route === 'OPPORTUNITIES') {
    const rows = buildOpportunityRows(state);
    body = `<h1>Earning Opportunities</h1>${table(
      ['Title', 'Category', 'Income Ladder', 'Compensation', 'Advertised', 'Expected Payout', 'Currency', 'Application', 'Qualification', 'Verification', 'Lifecycle'],
      rows.map((row) => [row.title, row.opportunityCategory, row.incomeLadderLevel, row.compensationType, row.advertisedCompensationValue, row.expectedPayoutValue, row.compensationCurrency, row.applicationRequired, row.qualificationRequired, row.verificationState, row.lifecycleState]),
    )}`;
  } else if (route === 'REVIEW_QUEUE') {
    body = `<h1>Review Queue</h1>${table(
      ['Queue ID', 'Version', 'Priority', 'State', 'Reasons'],
      state.reviewQueue.map((item) => [item.id, item.offerVersionId, item.priority, item.state, item.reasonCodes.join(', ')]),
    )}`;
  } else if (route === 'OPPORTUNITY_REVIEW') {
    const targetId = selectedId ?? state.reviewQueue.find((item) => item.state !== 'RESOLVED')?.offerVersionId;
    if (!targetId) body = '<h1>Opportunity Review</h1><p>No open review item.</p>';
    else {
      const detail = buildOpportunityReview(state, targetId);
      const v = detail.version;
      const evidenceHtml = detail.evidence.length === 0
        ? '<p>No bound evidence in this deterministic fixture.</p>'
        : table(['Field', 'Evidence', 'Confidence'], detail.evidence.map((item) => [item.fieldPath, item.evidenceText, item.confidence]));
      body = `<h1>Opportunity Review</h1><div class="review-grid"><section><h2>Normalized fields</h2>${table(
        ['Field', 'Value'],
        [
          ['Title', v.title], ['Category', v.opportunityCategory], ['Income ladder', v.incomeLadderLevel],
          ['Compensation type', v.compensationType], ['Advertised compensation', v.advertisedCompensationValue],
          ['Expected payout', v.expectedPayoutValue], ['Currency', v.compensationCurrency],
          ['Active minutes', v.estimatedActiveMinutes], ['Total effort minutes', v.estimatedTotalEffortMinutes],
          ['Application required', v.applicationRequired], ['Qualification required', v.qualificationRequired],
          ['Qualification probability', v.qualificationProbability], ['Countries/regions', v.eligibleCountriesOrRegions],
          ['Languages', v.languageRequirements], ['Skills', v.skillRequirements], ['Payout method', v.payoutMethod],
          ['Payout delay', v.payoutDelay], ['Repeatability', v.repeatability], ['Supply availability', v.supplyAvailabilityState],
          ['Destination', v.canonicalDestinationUrl],
        ],
      )}</section><section><h2>Source / evidence</h2><p>Snapshot: ${escapeHtml(detail.snapshot?.id ?? 'NULL / UNKNOWN')}</p>${evidenceHtml}</section><section><h2>Review context</h2><p>Queue: ${escapeHtml(detail.review?.id ?? 'NULL / UNKNOWN')}</p><p>Change: ${escapeHtml(detail.change?.summary ?? 'No material predecessor diff')}</p><p>Actions: APPROVE · MODIFY + APPROVE · REJECT · SEND BACK / RE-EXTRACT</p></section></div>`;
    }
  } else if (route === 'CHANGES') {
    body = `<h1>Material Changes</h1>${table(
      ['Change', 'Previous Version', 'Proposed Version', 'Type', 'Summary', 'Detected'],
      state.changes.map((change) => [change.id, change.previousVersionId, change.newVersionId, change.changeType, change.summary, change.detectedAt]),
    )}`;
  } else if (route === 'STALE_BROKEN') {
    body = `<h1>Stale / Broken</h1>${table(
      ['Incident', 'Source', 'Opportunity', 'Cause', 'State', 'Detail'],
      state.staleBroken.map((item) => [item.id, item.sourceId, item.offerId, item.cause, item.state, item.detail]),
    )}<p>Actions: RECHECK NOW · SUPPRESS OFFER · END OFFER · RETURN TO REVIEW · MARK SOURCE INCIDENT</p>`;
  } else {
    body = `<h1>Audit Log</h1>${table(
      ['Actor', 'Role', 'Action', 'Target', 'Before', 'After', 'Reason', 'Time'],
      state.auditLog.map((item) => [item.actorId, item.actorRole, item.action, `${item.targetType}:${item.targetId}`, item.beforeRef, item.afterRef, item.reason, item.createdAt]),
    )}`;
  }

  return `<!doctype html><html><head><meta charset="utf-8"><title>B64 Admin Console</title><style>body{font-family:system-ui,sans-serif;margin:24px;line-height:1.4}nav{margin-bottom:24px}table{border-collapse:collapse;width:100%;margin:12px 0 24px}th,td{border:1px solid #bbb;padding:6px;vertical-align:top;text-align:left}.review-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}@media(max-width:900px){.review-grid{grid-template-columns:1fr}}</style></head><body>${nav()}${statusLegend}${body}</body></html>`;
}
