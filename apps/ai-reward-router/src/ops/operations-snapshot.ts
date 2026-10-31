import { assessAdClickRuntimeConfig, type AdClickRuntimeConfigAssessment } from '../ad-click-first/provider-runtime-config.js';
import type { D1DatabaseLike } from '../income-pipeline/d1-user-income-repository.js';

/**
 * The real operational state behind the administrator view (issue #6001).
 *
 * Counts and configuration verdicts only — no member address, no session token,
 * no credential and no value that could leave the Worker in a response body by
 * accident. The provider half is the same assessment `npm run supply:check`
 * prints, so the console and the CLI cannot disagree about what is live.
 */

export interface B64RewardEventTally {
  readonly total: number;
  readonly pending: number;
  readonly confirmed: number;
  readonly reversed: number;
}

export interface B64OperationsSnapshot {
  readonly generatedAt: string;
  readonly storageConnected: boolean;
  readonly members: number;
  readonly googleLinkedMembers: number;
  readonly liveSessions: number;
  readonly incomeRecords: number;
  readonly rewardEvents: B64RewardEventTally;
  readonly providerAssessment: AdClickRuntimeConfigAssessment;
}

async function countWhere(
  db: D1DatabaseLike,
  sql: string,
  binds: readonly unknown[] = [],
): Promise<number> {
  const row = await db.prepare(sql).bind(...binds).first<{ n: number }>();
  return Number(row?.n ?? 0);
}

export async function readB64OperationsSnapshot(options: {
  readonly db: D1DatabaseLike | undefined;
  readonly env: Readonly<Record<string, string | undefined>>;
  readonly now?: Date;
}): Promise<B64OperationsSnapshot> {
  const now = options.now ?? new Date();
  const providerAssessment = assessAdClickRuntimeConfig(options.env);
  const base = Object.freeze({
    generatedAt: now.toISOString(),
    providerAssessment,
    allProvidersDisabled: providerAssessment.allDisabled,
  });

  if (!options.db) {
    return Object.freeze({
      ...base,
      storageConnected: false,
      members: 0,
      googleLinkedMembers: 0,
      liveSessions: 0,
      incomeRecords: 0,
      rewardEvents: Object.freeze({ total: 0, pending: 0, confirmed: 0, reversed: 0 }),
    });
  }

  const db = options.db;
  const tally = await db
    .prepare('SELECT state, COUNT(*) AS n FROM b64_reward_event GROUP BY state')
    .bind()
    .all<{ state: string; n: number }>();
  const rows = tally.results ?? [];
  const rewardEvents = Object.freeze({
    total: rows.reduce((sum, row) => sum + Number(row.n), 0),
    pending: rows.filter((row) => row.state === 'PENDING_PROVIDER_CONFIRMATION')
      .reduce((sum, row) => sum + Number(row.n), 0),
    confirmed: rows.filter((row) => row.state === 'CONFIRMED').reduce((sum, row) => sum + Number(row.n), 0),
    reversed: rows.filter((row) => row.state === 'REVERSED').reduce((sum, row) => sum + Number(row.n), 0),
  });

  return Object.freeze({
    ...base,
    storageConnected: true,
    members: await countWhere(db, 'SELECT COUNT(*) AS n FROM b64_member'),
    googleLinkedMembers: await countWhere(db, 'SELECT COUNT(*) AS n FROM b64_member_google'),
    liveSessions: await countWhere(
      db,
      'SELECT COUNT(*) AS n FROM b64_session WHERE revoked_at IS NULL AND expires_at > ?',
      [now.toISOString()],
    ),
    incomeRecords: await countWhere(db, 'SELECT COUNT(*) AS n FROM b64_user_income'),
    rewardEvents,
  });
}
