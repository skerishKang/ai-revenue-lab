import type { UserIncomeRecord } from './domain.js';

/**
 * Repository interface for user income records.
 * In-memory implementation for development/testing. Production implementation
 * uses the D1 adapter (see d1-user-income-repository.ts). The interface is the
 * contract that both implementations must satisfy.
 *
 * There is deliberately NO global "delete everything" operation on this
 * contract: production income records are per-user data, and no code path or
 * operator convenience may wipe every user's records at once. Test fixtures
 * reset their own test-only stores.
 */
export interface UserIncomeRepository {
  getByUser(userId: string): Promise<readonly UserIncomeRecord[]>;
  save(record: UserIncomeRecord): Promise<void>;
  delete(userId: string, recordId: string): Promise<boolean>;
}

/**
 * In-memory repository (PROTOTYPE — NOT durable persistence).
 * Records are lost on process restart or Worker isolate change.
 * Labeled as prototype until the D1 binding is available (all-clear required).
 * `clear()` exists on this class only so tests can reset the prototype store;
 * it is NOT part of the `UserIncomeRepository` contract and has no D1
 * counterpart.
 */
export class InMemoryUserIncomeRepository implements UserIncomeRepository {
  private readonly store = new Map<string, UserIncomeRecord[]>();

  async getByUser(userId: string): Promise<readonly UserIncomeRecord[]> {
    return Object.freeze([...(this.store.get(userId) ?? [])]);
  }

  async save(record: UserIncomeRecord): Promise<void> {
    const existing = this.store.get(record.userId) ?? [];
    const idx = existing.findIndex((r) => r.id === record.id);
    if (idx >= 0) {
      existing[idx] = record;
    } else {
      existing.push(record);
    }
    this.store.set(record.userId, existing);
  }

  async delete(userId: string, recordId: string): Promise<boolean> {
    const existing = this.store.get(userId);
    if (!existing) return false;
    const idx = existing.findIndex((r) => r.id === recordId);
    if (idx < 0) return false;
    existing.splice(idx, 1);
    this.store.set(userId, existing);
    return true;
  }

  async clear(): Promise<void> {
    this.store.clear();
  }

  // Sync access for prototype (not available in production D1 implementation)
  _syncStore: Map<string, UserIncomeRecord[]> = this.store;
}

// Singleton instance
let repository: UserIncomeRepository = new InMemoryUserIncomeRepository();

export function getRepository(): UserIncomeRepository {
  return repository;
}

export function setRepository(repo: UserIncomeRepository): void {
  repository = repo;
}

// Prototype sync wrappers (backed by in-memory store, NOT durable)
export function getUserRecords(userId: string): readonly UserIncomeRecord[] {
  const repo = repository as InMemoryUserIncomeRepository;
  return Object.freeze([...((repo as any)._syncStore?.get(userId) ?? [])]);
}

export function saveUserRecord(record: UserIncomeRecord): void {
  const repo = repository as InMemoryUserIncomeRepository;
  const store = (repo as any)._syncStore as Map<string, UserIncomeRecord[]>;
  const existing = store.get(record.userId) ?? [];
  const idx = existing.findIndex((r) => r.id === record.id);
  if (idx >= 0) {
    existing[idx] = record;
  } else {
    existing.push(record);
  }
  store.set(record.userId, existing);
  repository.save(record).catch(() => {});
}

export function deleteUserRecord(userId: string, recordId: string): boolean {
  const repo = repository as InMemoryUserIncomeRepository;
  const store = (repo as any)._syncStore as Map<string, UserIncomeRecord[]>;
  const existing = store.get(userId);
  if (!existing) return false;
  const idx = existing.findIndex((r) => r.id === recordId);
  if (idx < 0) return false;
  existing.splice(idx, 1);
  store.set(userId, existing);
  repository.delete(userId, recordId).catch(() => {});
  return true;
}

// Test-only reset for the prototype in-memory store. The production D1
// repository deliberately exposes no global delete path: nothing can wipe
// every user's income records at once.
export function clearStore(): void {
  const store = (repository as InMemoryUserIncomeRepository)._syncStore as
    | Map<string, UserIncomeRecord[]>
    | undefined;
  store?.clear();
}

export function getStoreSize(): number {
  const repo = repository as InMemoryUserIncomeRepository;
  const store = (repo as any)._syncStore as Map<string, UserIncomeRecord[]>;
  let total = 0;
  for (const records of store.values()) {
    total += records.length;
  }
  return total;
}
