import type { UserIncomeRecord } from './domain.js';

/**
 * Repository interface for user income records.
 * In-memory implementation for development/testing. Production implementation
 * will use D1/KV after all-clear. The interface is the contract that both
 * implementations must satisfy.
 */
export interface UserIncomeRepository {
  getByUser(userId: string): Promise<readonly UserIncomeRecord[]>;
  save(record: UserIncomeRecord): Promise<void>;
  delete(userId: string, recordId: string): Promise<boolean>;
  clear(): Promise<void>;
}

/**
 * In-memory repository (PROTOTYPE — NOT durable persistence).
 * Records are lost on process restart or Worker isolate change.
 * Labeled as prototype until D1/KV binding is available (all-clear required).
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

export function clearStore(): void {
  const repo = repository as InMemoryUserIncomeRepository;
  const store = (repo as any)._syncStore as Map<string, UserIncomeRecord[]>;
  store.clear();
  repository.clear().catch(() => {});
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
