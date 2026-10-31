# COM2 broker and identity staging bundle

This bundle is for later COM2 staging use only. Installation defaults to dry-run;
explicit `--apply` installs but does not start or enable either unit. Broker
and identity each have start, stop and status scripts; units bind only to
127.0.0.1 ports 8799 and 8802 respectively. Provision staging-only secret
files and an existing staged identity database separately. Never print secret
values. Broker install checks the pepper as the service user: an absolute,
regular, non-symlink file, owned by that user, mode 0600 or tighter, outside
the broker data/backup tree, and at least 32 characters.

Chat gateway settings (see #6380; document only, no Chat bundle edits):

- `PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED` (default off)
- `PADIEM_COM2_EDGE_SECRET_FILE`
- `PADIEM_COM2_EDGE_REPLAY_DB`
- `PADIEM_COM2_IDENTITY_RPC_SECRET_FILE`
- `PADIEM_COM2_BROKER_RPC_SECRET_FILE`

Chat's identity and broker RPC secret files must match the corresponding
staging service ingress secrets. Edge signing and stripping client-supplied
proof headers are separate prerequisites. Pairing and enrollment feature gates
remain off in the examples and require explicit staged configuration.
