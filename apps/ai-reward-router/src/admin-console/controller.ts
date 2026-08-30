import type { AdminRoute, AdminConsoleState, HealthCommand, ReviewCommand } from './domain.js';
import { renderAdminRoute } from './read-model.js';
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

function response(
  snapshot: AdminConsoleRepositorySnapshot,
  route: AdminRoute,
  selectedId?: string,
): AdminConsoleResponse {
  return Object.freeze({
    revision: snapshot.revision,
    route,
    selectedId: selectedId ?? null,
    html: renderAdminRoute(snapshot.state, route, selectedId),
    lastAuditId: snapshot.state.auditLog.at(-1)?.id ?? null,
  });
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
