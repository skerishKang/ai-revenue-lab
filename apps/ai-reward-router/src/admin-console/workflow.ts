import type {
  EarningOpportunity,
  OpportunityVersion,
  ReviewDecisionRecord,
  ReviewQueueItem,
} from '../persistence/domain.js';
import type {
  AdminAuditRecord,
  AdminConsoleState,
  HealthCommand,
  ReextractRequest,
  ReviewCommand,
  ReviewPatchRecord,
  StaleBrokenRecord,
} from './domain.js';

const EDITABLE_TERM_FIELDS = new Set<keyof OpportunityVersion>([
  'title', 'shortSummary', 'originalLanguage', 'opportunityCategory', 'incomeLadderLevel', 'compensationType',
  'advertisedCompensationValue', 'expectedPayoutValue', 'compensationCurrency', 'estimatedActiveMinutes',
  'estimatedTotalEffortMinutes', 'applicationMinutes', 'qualificationScreeningMinutes', 'preparationMinutes',
  'startLatencyMinutes', 'payoutMethod', 'payoutDelay', 'providerFees', 'repeatability', 'supplyAvailabilityState',
  'supplyObservedAt', 'applicationRequired', 'qualificationRequired', 'qualificationProbability', 'acceptanceProbability',
  'eligibleCountriesOrRegions', 'languageRequirements', 'skillRequirements', 'deviceOsRequirements',
  'identityKycRequirements', 'ageRequirements', 'taxContractorRequirements', 'schedulingRequirements',
  'canonicalDestinationUrl',
]);

function requireReviewRole(role: ReviewCommand['role']): void {
  if (role !== 'ADMIN' && role !== 'REVIEWER') throw new Error(`Role ${role} cannot perform opportunity review actions`);
}

function requireHealthRole(role: HealthCommand['role']): void {
  if (role !== 'ADMIN' && role !== 'OPERATOR') throw new Error(`Role ${role} cannot perform stale/broken operations`);
}

function replaceById<T extends { readonly id: string }>(items: readonly T[], replacement: T): readonly T[] {
  return Object.freeze(items.map((item) => item.id === replacement.id ? replacement : item));
}

function resolveQueue(item: ReviewQueueItem, at: string): ReviewQueueItem {
  return Object.freeze({ ...item, state: 'RESOLVED', resolvedAt: at });
}

function versionAudit(command: ReviewCommand, version: OpportunityVersion, action: string, afterRef: string | null): AdminAuditRecord {
  return Object.freeze({
    id: command.auditId,
    actorId: command.actorId,
    actorRole: command.role,
    action,
    targetType: 'OPPORTUNITY_VERSION',
    targetId: version.id,
    beforeRef: `${version.id}:${version.verificationState}`,
    afterRef,
    reason: command.reason,
    createdAt: command.at,
    modelId: version.modelId,
    promptVersion: version.promptVersion,
    sourceSnapshotHash: version.sourceSnapshotHash,
  });
}

function reviewedOpportunity(opportunity: EarningOpportunity, versionId: string): EarningOpportunity {
  return Object.freeze({ ...opportunity, lifecycleState: 'VERIFIED', currentVersionId: versionId });
}

function validatePatch(patch: Readonly<Record<string, unknown>>): void {
  const forbidden = Object.keys(patch).filter((field) => !EDITABLE_TERM_FIELDS.has(field as keyof OpportunityVersion));
  if (forbidden.length > 0) throw new Error(`Reviewer patch contains non-term or identity fields: ${forbidden.join(', ')}`);
}

function patchVersion(
  source: OpportunityVersion,
  resultingVersionId: string,
  patch: Readonly<Record<string, unknown>>,
  createdAt: string,
): OpportunityVersion {
  validatePatch(patch);
  return Object.freeze({
    ...source,
    ...patch,
    id: resultingVersionId,
    versionNumber: source.versionNumber + 1,
    verificationState: 'VERIFIED',
    createdAt,
  }) as OpportunityVersion;
}

export function applyReviewCommand(state: AdminConsoleState, command: ReviewCommand): AdminConsoleState {
  requireReviewRole(command.role);
  if (!command.actorId.trim() || !command.reason.trim() || !command.auditId.trim()) throw new Error('Review action requires actorId, reason, and auditId');
  if (state.auditLog.some((item) => item.id === command.auditId)) throw new Error(`auditId already exists: ${command.auditId}`);
  if (command.action !== 'RE_EXTRACT') {
    if (!command.decisionId.trim()) throw new Error('Review decision action requires decisionId');
    if (state.reviewDecisions.some((item) => item.id === command.decisionId)) throw new Error(`decisionId already exists: ${command.decisionId}`);
  }
  const queue = state.reviewQueue.find((item) => item.id === command.reviewQueueId);
  if (!queue) throw new Error(`Unknown review queue item: ${command.reviewQueueId}`);
  if (queue.state === 'RESOLVED') throw new Error(`Review queue item is already resolved: ${queue.id}`);
  const version = state.versions.find((item) => item.id === queue.offerVersionId);
  if (!version) throw new Error(`Missing version for review queue item: ${queue.id}`);
  if (version.verificationState !== 'REVIEW_REQUIRED') throw new Error(`Version is not REVIEW_REQUIRED: ${version.id}`);
  const opportunity = state.opportunities.find((item) => item.id === version.offerId);
  if (!opportunity) throw new Error(`Missing opportunity for version: ${version.id}`);

  const nextQueue = replaceById(state.reviewQueue, resolveQueue(queue, command.at));
  let versions = state.versions;
  let opportunities = state.opportunities;
  let decisions = state.reviewDecisions;
  let patches = state.reviewPatches;
  let reextractRequests = state.reextractRequests;
  let audit: AdminAuditRecord;

  if (command.action === 'APPROVE') {
    const approved = Object.freeze({ ...version, verificationState: 'VERIFIED' as const });
    versions = replaceById(versions, approved);
    opportunities = replaceById(opportunities, reviewedOpportunity(opportunity, approved.id));
    const decision: ReviewDecisionRecord = Object.freeze({
      id: command.decisionId, reviewQueueId: queue.id, offerVersionId: approved.id, decision: 'APPROVE', reviewerId: command.actorId,
      approvalReason: command.reason, rejectionReason: null, patch: null, createdAt: command.at,
    });
    decisions = Object.freeze([...decisions, decision]);
    audit = versionAudit(command, version, 'REVIEW_APPROVE', `${approved.id}:VERIFIED`);
  } else if (command.action === 'MODIFY_APPROVE') {
    const patch = command.patch;
    const patchId = command.patchId?.trim();
    const resultingVersionId = command.resultingVersionId?.trim();
    if (!patch || Object.keys(patch).length === 0) throw new Error('MODIFY_APPROVE requires a non-empty reviewer patch');
    if (!patchId) throw new Error('MODIFY_APPROVE requires patchId');
    if (state.reviewPatches.some((item) => item.id === patchId)) throw new Error(`patchId already exists: ${patchId}`);
    if (!resultingVersionId) throw new Error('MODIFY_APPROVE requires resultingVersionId');
    if (state.versions.some((item) => item.id === resultingVersionId)) throw new Error(`resultingVersionId already exists: ${resultingVersionId}`);
    const resulting = patchVersion(version, resultingVersionId, patch, command.at);
    versions = Object.freeze([...versions, resulting]);
    opportunities = replaceById(opportunities, reviewedOpportunity(opportunity, resulting.id));
    const patchRecord: ReviewPatchRecord = Object.freeze({
      id: patchId, reviewQueueId: queue.id, fromVersionId: version.id, resultingVersionId: resulting.id,
      reviewerId: command.actorId, patch: Object.freeze({ ...patch }), reason: command.reason, createdAt: command.at,
    });
    patches = Object.freeze([...patches, patchRecord]);
    const decision: ReviewDecisionRecord = Object.freeze({
      id: command.decisionId, reviewQueueId: queue.id, offerVersionId: resulting.id, decision: 'MODIFY_APPROVE', reviewerId: command.actorId,
      approvalReason: command.reason, rejectionReason: null, patch: patchRecord.patch, createdAt: command.at,
    });
    decisions = Object.freeze([...decisions, decision]);
    audit = versionAudit(command, version, 'REVIEW_MODIFY_APPROVE', `${resulting.id}:VERIFIED`);
  } else if (command.action === 'REJECT') {
    const rejected = Object.freeze({ ...version, verificationState: 'REJECTED' as const });
    versions = replaceById(versions, rejected);
    if (opportunity.currentVersionId === null) {
      opportunities = replaceById(opportunities, Object.freeze({ ...opportunity, lifecycleState: 'REJECTED' as const }));
    }
    const decision: ReviewDecisionRecord = Object.freeze({
      id: command.decisionId, reviewQueueId: queue.id, offerVersionId: rejected.id, decision: 'REJECT', reviewerId: command.actorId,
      approvalReason: null, rejectionReason: command.reason, patch: null, createdAt: command.at,
    });
    decisions = Object.freeze([...decisions, decision]);
    audit = versionAudit(command, version, 'REVIEW_REJECT', `${rejected.id}:REJECTED`);
  } else {
    const requestId = command.reextractRequestId?.trim();
    if (!requestId) throw new Error('RE_EXTRACT requires reextractRequestId');
    if (state.reextractRequests.some((item) => item.id === requestId)) throw new Error(`reextractRequestId already exists: ${requestId}`);
    const request: ReextractRequest = Object.freeze({
      id: requestId, reviewQueueId: queue.id, offerVersionId: version.id, requestedBy: command.actorId,
      reason: command.reason, sourceSnapshotId: version.sourceSnapshotId, createdAt: command.at,
    });
    reextractRequests = Object.freeze([...reextractRequests, request]);
    audit = versionAudit(command, version, 'REVIEW_RE_EXTRACT', `${request.id}:REQUESTED`);
  }

  return Object.freeze({
    ...state,
    versions,
    opportunities,
    reviewQueue: nextQueue,
    reviewDecisions: decisions,
    reviewPatches: patches,
    reextractRequests,
    auditLog: Object.freeze([...state.auditLog, audit]),
  });
}

function healthAudit(command: HealthCommand, incident: StaleBrokenRecord, afterRef: string): AdminAuditRecord {
  return Object.freeze({
    id: command.auditId,
    actorId: command.actorId,
    actorRole: command.role,
    action: `STALE_BROKEN_${command.action}`,
    targetType: 'STALE_BROKEN',
    targetId: incident.id,
    beforeRef: `${incident.id}:${incident.state}`,
    afterRef,
    reason: command.reason,
    createdAt: command.at,
    modelId: null,
    promptVersion: null,
    sourceSnapshotHash: null,
  });
}

export function applyHealthCommand(state: AdminConsoleState, command: HealthCommand): AdminConsoleState {
  requireHealthRole(command.role);
  if (!command.actorId.trim() || !command.reason.trim() || !command.auditId.trim()) throw new Error('Stale/broken action requires actorId, reason, and auditId');
  if (state.auditLog.some((item) => item.id === command.auditId)) throw new Error(`auditId already exists: ${command.auditId}`);
  const incident = state.staleBroken.find((item) => item.id === command.incidentId);
  if (!incident) throw new Error(`Unknown stale/broken incident: ${command.incidentId}`);
  if (incident.state === 'RESOLVED') throw new Error(`Incident is already resolved: ${incident.id}`);

  let staleBroken = state.staleBroken;
  let opportunities = state.opportunities;
  let reviewQueue = state.reviewQueue;
  let nextIncident = incident;

  if (command.action === 'RECHECK_NOW') {
    nextIncident = Object.freeze({ ...incident, state: 'RECHECK_REQUESTED' });
  } else if (command.action === 'MARK_SOURCE_INCIDENT') {
    nextIncident = Object.freeze({ ...incident, state: 'SOURCE_INCIDENT' });
  } else {
    if (!incident.offerId) throw new Error(`${command.action} requires an opportunity-linked incident`);
    const opportunity = state.opportunities.find((item) => item.id === incident.offerId);
    if (!opportunity) throw new Error(`Missing opportunity for incident: ${incident.id}`);
    if (command.action === 'SUPPRESS_OFFER') {
      opportunities = replaceById(opportunities, Object.freeze({ ...opportunity, lifecycleState: 'STALE' as const }));
      nextIncident = Object.freeze({ ...incident, state: 'RESOLVED' });
    } else if (command.action === 'END_OFFER') {
      opportunities = replaceById(opportunities, Object.freeze({ ...opportunity, lifecycleState: 'ENDED' as const }));
      nextIncident = Object.freeze({ ...incident, state: 'RESOLVED' });
    } else {
      const queueId = command.reviewQueueId?.trim();
      if (!queueId) throw new Error('RETURN_TO_REVIEW requires reviewQueueId');
      if (state.reviewQueue.some((item) => item.id === queueId)) throw new Error(`reviewQueueId already exists: ${queueId}`);
      const targetVersionId = opportunity.currentVersionId ?? state.versions
        .filter((item) => item.offerId === opportunity.id)
        .sort((a, b) => b.versionNumber - a.versionNumber)[0]?.id;
      if (!targetVersionId) throw new Error(`No version available to return to review: ${opportunity.id}`);
      if (state.reviewQueue.some((item) => item.offerVersionId === targetVersionId && item.state !== 'RESOLVED')) {
        throw new Error(`An active review queue item already exists for version: ${targetVersionId}`);
      }
      opportunities = replaceById(opportunities, Object.freeze({ ...opportunity, lifecycleState: 'REVIEW_REQUIRED' as const }));
      reviewQueue = Object.freeze([...reviewQueue, Object.freeze({
        id: queueId, offerVersionId: targetVersionId, reasonCodes: Object.freeze(['STALE_BROKEN_RETURN']), priority: 'HIGH' as const,
        state: 'OPEN' as const, assignedTo: null, createdAt: command.at, resolvedAt: null,
      })]);
      nextIncident = Object.freeze({ ...incident, state: 'RESOLVED' });
    }
  }

  staleBroken = replaceById(staleBroken, nextIncident);
  const audit = healthAudit(command, incident, `${nextIncident.id}:${nextIncident.state}`);
  return Object.freeze({
    ...state,
    staleBroken,
    opportunities,
    reviewQueue,
    auditLog: Object.freeze([...state.auditLog, audit]),
  });
}
