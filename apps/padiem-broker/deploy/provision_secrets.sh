#!/usr/bin/env bash
# Generates the two broker secrets ONCE on the host. Values are written to
# 0600 files and never printed, logged or committed; the pepper file is kept
# OUT of the database backup folder on purpose (design §4).
set -euo pipefail
umask 077
dir=${1:-/opt/padiem/broker/secrets}
install -d -m 0700 "$dir"
gen() {
  local name=$1
  local path="$dir/$name"
  if [[ -s "$path" ]]; then
    printf '%s\n' "BROKER_SECRET=$name EXISTS"
    return 0
  fi
  python3 -c 'import secrets; print(secrets.token_hex(32))' > "$path"
  chmod 0600 "$path"
  printf '%s\n' "BROKER_SECRET=$name CREATED"
}
gen rpc_ingress_secret
gen pepper
printf '%s\n' 'BROKER_SECRETS=PASS' 'VALUES_PRINTED=NO' 'BACKUP_INCLUSION=NO'
