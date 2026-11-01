// Record-level reconciliation for the BookAI / COM2 v1 protocol.
const kinds = new Set(['progress','note','highlight','ai_chat']);
export function validateRecord(record) {
  if (!record || typeof record !== 'object' || Array.isArray(record) ||
      typeof record.record_id !== 'string' || !record.record_id ||
      typeof record.book_id !== 'string' || !record.book_id ||
      typeof record.locator !== 'string' || !record.locator || !kinds.has(record.kind) ||
      !Number.isSafeInteger(record.updated_at) || record.updated_at < 0 ||
      typeof record.deleted !== 'boolean' || !record.payload ||
      typeof record.payload !== 'object' || Array.isArray(record.payload)) throw new Error('invalid_record');
  return record;
}
export function mergeRecords(current, incoming) {
  const records = new Map();
  for (const record of current) { validateRecord(record); records.set(record.record_id, structuredClone(record)); }
  for (const record of incoming) {
    validateRecord(record);
    const old = records.get(record.record_id);
    if (!old || record.updated_at > old.updated_at) records.set(record.record_id, structuredClone(record));
  }
  return Array.from(records.values());
}
