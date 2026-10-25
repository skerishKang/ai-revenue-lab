export const INCOME_PIPELINE_STATUSES = [
  'SAVED', 'APPLIED', 'IN_REVIEW', 'ACCEPTED', 'IN_PROGRESS',
  'COMPLETED', 'PAID', 'REJECTED', 'EXPIRED', 'CANCELLED',
] as const;
export type IncomePipelineStatus = (typeof INCOME_PIPELINE_STATUSES)[number];

export const INCOME_PIPELINE_ACTIVE_STATUSES: readonly IncomePipelineStatus[] = Object.freeze([
  'SAVED', 'APPLIED', 'IN_REVIEW', 'ACCEPTED', 'IN_PROGRESS',
]);

export const INCOME_PIPELINE_TERMINAL_STATUSES: readonly IncomePipelineStatus[] = Object.freeze([
  'COMPLETED', 'PAID', 'REJECTED', 'EXPIRED', 'CANCELLED',
]);

export const INCOME_PIPELINE_STATUS_LABELS: Readonly<Record<IncomePipelineStatus, string>> = Object.freeze({
  SAVED: '저장됨',
  APPLIED: '신청함',
  IN_REVIEW: '심사 중',
  ACCEPTED: '선발됨',
  IN_PROGRESS: '진행 중',
  COMPLETED: '완료',
  PAID: '지급 완료',
  REJECTED: '거절됨',
  EXPIRED: '만료됨',
  CANCELLED: '취소됨',
});

export const INCOME_PIPELINE_STATUS_ORDER: Readonly<Record<IncomePipelineStatus, number>> = Object.freeze({
  SAVED: 0, APPLIED: 1, IN_REVIEW: 2, ACCEPTED: 3, IN_PROGRESS: 4,
  COMPLETED: 5, PAID: 6, REJECTED: 7, EXPIRED: 8, CANCELLED: 9,
});

export const INCOME_PIPELINE_TRANSITIONS: Readonly<Record<IncomePipelineStatus, readonly IncomePipelineStatus[]>> = Object.freeze({
  SAVED: Object.freeze(['APPLIED', 'CANCELLED', 'EXPIRED'] as readonly IncomePipelineStatus[]),
  APPLIED: Object.freeze(['IN_REVIEW', 'ACCEPTED', 'REJECTED', 'CANCELLED', 'EXPIRED'] as readonly IncomePipelineStatus[]),
  IN_REVIEW: Object.freeze(['ACCEPTED', 'REJECTED', 'CANCELLED', 'EXPIRED'] as readonly IncomePipelineStatus[]),
  ACCEPTED: Object.freeze(['IN_PROGRESS', 'CANCELLED', 'EXPIRED'] as readonly IncomePipelineStatus[]),
  IN_PROGRESS: Object.freeze(['COMPLETED', 'CANCELLED', 'EXPIRED'] as readonly IncomePipelineStatus[]),
  COMPLETED: Object.freeze(['PAID', 'CANCELLED'] as readonly IncomePipelineStatus[]),
  PAID: Object.freeze([] as readonly IncomePipelineStatus[]),
  REJECTED: Object.freeze(['SAVED'] as readonly IncomePipelineStatus[]),
  EXPIRED: Object.freeze(['SAVED'] as readonly IncomePipelineStatus[]),
  CANCELLED: Object.freeze(['SAVED'] as readonly IncomePipelineStatus[]),
});

export function isValidIncomePipelineTransition(
  from: IncomePipelineStatus,
  to: IncomePipelineStatus,
): boolean {
  return INCOME_PIPELINE_TRANSITIONS[from].includes(to);
}

export type IncomeSourceType = 'AD_CLICK' | 'PUBLIC_OPPORTUNITY' | 'EXTERNAL_JOB' | 'MANUAL';
export type IncomeCurrency = 'KRW' | 'USD' | 'EUR' | 'GBP' | 'JPY' | 'OTHER';

export interface UserIncomeRecord {
  readonly id: string;
  readonly userId: string;
  readonly opportunityId: string | null;
  readonly externalRef: string | null;
  readonly sourceType: IncomeSourceType;
  readonly title: string;
  readonly vendor: string;
  readonly status: IncomePipelineStatus;
  readonly expectedAmount: number | null;
  readonly expectedCurrency: IncomeCurrency | null;
  readonly actualAmount: number | null;
  readonly actualCurrency: IncomeCurrency | null;
  readonly appliedAt: string | null;
  readonly acceptedAt: string | null;
  readonly completedAt: string | null;
  readonly paidAt: string | null;
  readonly expiresAt: string | null;
  readonly note: string | null;
  readonly sourceUrl: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface UserIncomeSummary {
  readonly totalRecords: number;
  readonly activeCount: number;
  readonly completedCount: number;
  readonly paidCount: number;
  readonly expectedTotal: ReadonlyMap<IncomeCurrency, number>;
  readonly actualTotal: ReadonlyMap<IncomeCurrency, number>;
}

export function validateUserIncomeRecord(record: UserIncomeRecord): readonly string[] {
  const errors: string[] = [];
  if (!record.id.trim()) errors.push('id is required');
  if (!record.userId.trim()) errors.push('userId is required');
  if (!record.title.trim()) errors.push('title is required');
  if (!record.vendor.trim()) errors.push('vendor is required');
  if (!INCOME_PIPELINE_STATUSES.includes(record.status)) errors.push('invalid status');
  if (record.expectedAmount !== null && record.expectedAmount < 0) errors.push('expectedAmount must be >= 0');
  if (record.actualAmount !== null && record.actualAmount < 0) errors.push('actualAmount must be >= 0');
  if (record.expectedAmount !== null && record.expectedCurrency === null) errors.push('expectedCurrency required when expectedAmount set');
  if (record.actualAmount !== null && record.actualCurrency === null) errors.push('actualCurrency required when actualAmount set');
  if (record.paidAt !== null && record.status !== 'PAID') errors.push('paidAt only valid for PAID status');
  if (record.completedAt !== null && !['COMPLETED', 'PAID'].includes(record.status)) errors.push('completedAt only valid for COMPLETED/PAID');
  return Object.freeze(errors);
}

export type UserIncomeLoader = (
  request: Request,
  userId: string | null,
) => Promise<readonly UserIncomeRecord[]> | readonly UserIncomeRecord[];

export function buildUserIncomeSummary(records: readonly UserIncomeRecord[]): UserIncomeSummary {
  const expectedTotal = new Map<IncomeCurrency, number>();
  const actualTotal = new Map<IncomeCurrency, number>();
  let activeCount = 0;
  let completedCount = 0;
  let paidCount = 0;

  for (const record of records) {
    if (INCOME_PIPELINE_ACTIVE_STATUSES.includes(record.status)) activeCount++;
    if (record.status === 'COMPLETED') completedCount++;
    if (record.status === 'PAID') { completedCount++; paidCount++; }
    if (record.expectedAmount !== null && record.expectedCurrency !== null) {
      const cur = record.expectedCurrency;
      expectedTotal.set(cur, (expectedTotal.get(cur) ?? 0) + record.expectedAmount);
    }
    if (record.actualAmount !== null && record.actualCurrency !== null) {
      const cur = record.actualCurrency;
      actualTotal.set(cur, (actualTotal.get(cur) ?? 0) + record.actualAmount);
    }
  }

  return Object.freeze({
    totalRecords: records.length,
    activeCount,
    completedCount,
    paidCount,
    expectedTotal: new Map(expectedTotal),
    actualTotal: new Map(actualTotal),
  });
}

export function filterUserIncomeRecords(
  records: readonly UserIncomeRecord[],
  filters: { status?: IncomePipelineStatus | null; vendor?: string | null },
): readonly UserIncomeRecord[] {
  return Object.freeze(
    records.filter((r) => {
      if (filters.status && r.status !== filters.status) return false;
      if (filters.vendor && r.vendor !== filters.vendor) return false;
      return true;
    }),
  );
}

export function sortUserIncomeRecords(records: readonly UserIncomeRecord[]): readonly UserIncomeRecord[] {
  return Object.freeze(
    [...records].sort((a, b) => {
      const statusDiff = INCOME_PIPELINE_STATUS_ORDER[a.status] - INCOME_PIPELINE_STATUS_ORDER[b.status];
      if (statusDiff !== 0) return statusDiff;
      return Date.parse(b.updatedAt) - Date.parse(a.updatedAt);
    }),
  );
}

export function canUserAccessRecord(record: UserIncomeRecord, userId: string): boolean {
  return record.userId === userId;
}

export function formatCurrencyAmount(amount: number | null, currency: string | null): string {
  if (amount === null || currency === null) return '미확인';
  return amount.toLocaleString() + ' ' + currency;
}

export function formatIncomeDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  const kst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const yyyy = kst.getUTCFullYear();
  const mm = String(kst.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(kst.getUTCDate()).padStart(2, '0');
  return yyyy + '.' + mm + '.' + dd;
}
