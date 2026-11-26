import { DatabaseSync } from 'node:sqlite';

export function openStateDatabase(path) {
  const database = new DatabaseSync(path);
  database.exec('PRAGMA journal_mode=WAL');
  database.exec('PRAGMA synchronous=NORMAL');
  database.exec('PRAGMA foreign_keys=ON');
  database.exec('PRAGMA busy_timeout=5000');
  database.exec('PRAGMA wal_autocheckpoint=1000');
  return database;
}

export function sqliteAdapter(database) {
  return {
    exec(query, ...params) {
      const statement = database.prepare(query);
      if (statement.columns().length) return { toArray: () => statement.all(...params) };
      statement.run(...params);
      return { toArray: () => [] };
    },
  };
}

export function transactionSync(database, operation) {
  if (database.isTransaction) return operation();
  database.exec('BEGIN IMMEDIATE');
  try {
    const result = operation();
    database.exec('COMMIT');
    return result;
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  }
}
