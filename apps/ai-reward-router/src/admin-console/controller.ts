import type {
  AdminConsoleState,
  AdminRole,
  AdminRoute,
  AdminReviewAction,
  HealthCommand,
  ReviewCommand,
} from './domain.js';
import { renderOperatorAdminRoute } from './operator-surface.js';
import { applyHealthCommand, applyReviewCommand } from './workflow.js';

export interface AdminConsoleRepositorySnapshot {
  readonly revision: number;
  readonly state: AdminConsoleState;
}

export interface AdminConsoleRepository {
  read(): AdminConsoleRepositorySnapshot;
  replace(expectedRevision: number, nextState: AdminConsoleState): AdminConsoleRepositorySnapshot;
}

export class InMemoryAdminConsoleRepository implements AdminConsoleRepository {
  #revision = 0;
  #state: AdminConsoleState;

  constructor(initialState: AdminConsoleState) {
    this.#state = initialState;
  }

  read(): AdminConsoleRepositorySnapshot {
    return Object.freeze({ revision: this.#revision, state: this.#state });
  }

  replace(expectedRevision: number, nextState: AdminConsoleState): AdminConsoleRepositorySnapshot {
    if (expectedRevision !== this.#revision) {
      throw new Error(`Admin console repository revision conflict: expected ${expectedRevision}, actual ${this.#revision}`);
    }
    this.#state = nextState;
    this.#revision += 1;
    return this.read();
  }
}

export type AdminConsoleRequest =
  | Readonly<{
      kind: 'GET';
      route: AdminRoute;
      selectedId?: string;
    }>
  | Readonly<{
      kind: 'REVIEW';
      command: ReviewCommand;
      returnRoute?: AdminRoute;
      selectedId?: string;
    }>
  | Readonly<{
      kind: 'HEALTH';
      command: HealthCommand;
      returnRoute?: AdminRoute;
      selectedId?: string;
    }>;

export interface AdminConsoleResponse {
  readonly revision: number;
  readonly route: AdminRoute;
  readonly selectedId: string | null;
  readonly html: string;
  readonly lastAuditId: string | null;
}

export interface AdminPrincipal {
  readonly actorId: string;
  readonly role: AdminRole;
}

export interface AdminReviewFormSubmission {
  readonly action: AdminReviewAction;
  readonly reviewQueueId: string;
  readonly selectedId?: string;
  readonly reason: string;
  readonly resultingVersionId?: string;
  readonly patchJson?: string;
}

export interface AdminMutationContext {
  readonly at: string;
  readonly idempotencyKey: string;
}

function response(
  snapshot: AdminConsoleRepositorySnapshot,
  route: AdminRoute,
  selectedId?: string,
): AdminConsoleResponse {
  return Object.freeze({
    revision: snapshot.revision,
    route,
    selectedId: selectedId ?? null,
    html: renderOperatorAdminRoute(snapshot.state, route, selectedId),
    lastAuditId: snapshot.state.auditLog.at(-1)?.id ?? null,
  });
}

function requireNonBlank(value: string | undefined, field: string): string {
  const normalized = value?.trim() ?? '';
  if (normalized.length === 0) throw new Error(`${field} is required`);
  return normalized;
}

function parseReviewPatch(value: string | undefined): Readonly<Record<string, unknown>> {
  const raw = requireNonBlank(value, 'patchJson');
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('patchJson must be valid JSON');
  }
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('patchJson must be a JSON object');
  }
  return Object.freeze({ ...(parsed as Record<string, unknown>) });
}

export function handleAdminConsoleRequest(
  repository: AdminConsoleRepository,
  request: AdminConsoleRequest,
): AdminConsoleResponse {
  const snapshot = repository.read();
  if (request.kind === 'GET') {
    return response(snapshot, request.route, request.selectedId);
  }

  if (request.kind === 'REVIEW') {
    const nextState = applyReviewCommand(snapshot.state, request.command);
    const committed = repository.replace(snapshot.revision, nextState);
    return response(committed, request.returnRoute ?? 'REVIEW_QUEUE', request.selectedId);
  }

  const nextState = applyHealthCommand(snapshot.state, request.command);
  const committed = repository.replace(snapshot.revision, nextState);
  return response(committed, request.returnRoute ?? 'STALE_BROKEN', request.selectedId);
}

export function handleAdminReviewFormSubmission(
  repository: AdminConsoleRepository,
  principal: AdminPrincipal,
  submission: AdminReviewFormSubmission,
  context: AdminMutationContext,
): AdminConsoleResponse {
  const reviewQueueId = requireNonBlank(submission.reviewQueueId, 'reviewQueueId');
  const reason = requireNonBlank(submission.reason, 'reason');
  const key = requireNonBlank(context.idempotencyKey, 'idempotencyKey');
  const at = requireNonBlank(context.at, 'at');

  const base: ReviewCommand = {
    action: submission.action,
    role: principal.role,
    actorId: requireNonBlank(principal.actorId, 'actorId'),
    reviewQueueId,
    decisionId: `decision-${key}`,
    auditId: `audit-${key}`,
    reason,
    at,
  };

  let command: ReviewCommand = base;
  if (submission.action === 'MODIFY_APPROVE') {
    command = {
      ...base,
      patchId: `patch-${key}`,
      resultingVersionId: requireNonBlank(submission.resultingVersionId, 'resultingVersionId'),
      patch: parseReviewPatch(submission.patchJson),
    };
  } else if (submission.action === 'RE_EXTRACT') {
    command = { ...base, reextractRequestId: `reextract-${key}` };
  }

  return handleAdminConsoleRequest(repository, {
    kind: 'REVIEW',
    command,
    returnRoute: 'OPPORTUNITY_REVIEW',
    selectedId: submission.selectedId,
  });
}
