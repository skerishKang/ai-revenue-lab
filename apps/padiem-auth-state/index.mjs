import { dirname } from 'node:path';
import { existsSync } from 'node:fs';
import { createDeletionRecordRpc, createIdentityAuthorityRpc } from './identity-rpc.mjs';
import { createStateService } from './server.mjs';
import { openStateDatabase } from './sqlite.mjs';

function required(name) {
  const value = process.env[name];
  if (typeof value !== 'string' || !value.trim()) throw new Error(`missing_${name.toLowerCase()}`);
  return value;
}

const databasePath = required('PADIEM_AUTH_STATE_DB');
if (!existsSync(dirname(databasePath))) throw new Error('state_database_directory_missing');
const identityOrigin = required('PADIEM_AUTH_STATE_IDENTITY_RPC_ORIGIN');
const deletionOrigin = required('PADIEM_AUTH_STATE_DELETION_RECORD_ORIGIN');
const env = {
  IDENTITY_AUTHORITY: createIdentityAuthorityRpc({
    origin: identityOrigin,
    secret: required('PADIEM_AUTH_STATE_IDENTITY_RPC_SECRET'),
  }),
  COMMON_LOGIN_DELETION_RECORD: createDeletionRecordRpc({
    origin: deletionOrigin,
    secret: required('PADIEM_AUTH_STATE_DELETION_RECORD_RPC_SECRET'),
  }),
  PADIEM_AUTH_ACCOUNT_ISSUER_MODE: process.env.PADIEM_AUTH_ACCOUNT_ISSUER_MODE,
  PADIEM_AUTH_EMAIL_RECOVERY_ENABLED: process.env.PADIEM_AUTH_EMAIL_RECOVERY_ENABLED,
  PADIEM_AUTH_PASSWORD_FIND_ENABLED: process.env.PADIEM_AUTH_PASSWORD_FIND_ENABLED,
  PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED: process.env.PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED,
};
const database = openStateDatabase(databasePath);
const service = createStateService({ database, secret: required('PADIEM_AUTH_STATE_SECRET'), env });
const port = Number(process.env.PADIEM_AUTH_STATE_PORT || 8787);
const host = process.env.PADIEM_AUTH_STATE_HOST || 'localhost';
if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw new Error('state_port_invalid');

const maintenanceTimer = setInterval(() => {
  try { service.maintenance(); } catch { console.error(JSON.stringify({ auth_stage: 'auth_state_maintenance_failed' })); }
}, 60_000);
maintenanceTimer.unref();

let closing = false;
function close() {
  if (closing) return;
  closing = true;
  clearInterval(maintenanceTimer);
  service.server.close(() => {
    database.close();
    process.exit(0);
  });
}
process.once('SIGTERM', close);
process.once('SIGINT', close);

service.server.on('error', () => {
  console.error(JSON.stringify({ auth_stage: 'auth_state_service_listen_failed' }));
  database.close();
  process.exit(1);
});
service.server.listen(port, host, () => {
  console.log(JSON.stringify({ auth_stage: 'auth_state_service_started' }));
});
