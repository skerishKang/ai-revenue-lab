import type { UserIncomeRecord } from './domain.js';

/**
 * In-memory store for user income records.
 * Keyed by userId. In production, this would be backed by D1/KV.
 * For now, provides the storage boundary that CRUD operations use.
 */
const store = new Map<string, UserIncomeRecord[]>();

export function getUserRecords(userId: string): readonly UserIncomeRecord[] {
  return Object.freeze([...(store.get(userId) ?? [])]);
}

export function saveUserRecord(record: UserIncomeRecord): void {
  const existing = store.get(record.userId) ?? [];
  const idx = existing.findIndex((r) => r.id === record.id);
  if (idx >= 0) {
    existing[idx] = record;
  } else {
    existing.push(record);
  }
  store.set(record.userId, existing);
}

export function deleteUserRecord(userId: string, recordId: string): boolean {
  const existing = store.get(userId);
  if (!existing) return false;
  const idx = existing.findIndex((r) => r.id === recordId);
  if (idx < 0) return false;
  existing.splice(idx, 1);
  store.set(userId, existing);
  return true;
}

export function clearStore(): void {
  store.clear();
}

export function getStoreSize(): number {
  let total = 0;
  for (const records of store.values()) {
    total += records.length;
  }
  return total;
}
