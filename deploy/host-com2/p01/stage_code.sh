#!/usr/bin/env bash
# Stage a complete Engine tree under the installation root without touching services.
set -euo pipefail
source_root=${1:?source root required}
root=${2:?installation root required}
source_engine="$source_root/apps/padiem-ai-engine"
fail() { echo "P01_COM2_INSTALL=$1" >&2; exit 1; }
[[ -f "$source_engine/asgi.py" ]] || fail ASGI_ENTRY_MISSING
for item in app clients ingress migrations asgi.py worker.py worker_identity.py; do
  [[ -e "$source_engine/$item" ]] || fail SOURCE_MISSING
done
[[ -d "$root" ]] || fail APP_ROOT_MISSING
install -d -m 0755 "$root/releases" "$root/rollback"
release=$(mktemp -d "$root/releases/p01.XXXXXXXX")
chmod 0755 "$release"
for item in app clients ingress migrations asgi.py worker.py worker_identity.py; do
  cp -aL "$source_engine/$item" "$release/$item"
done
[[ -f "$release/asgi.py" ]] || fail ASGI_ENTRY_MISSING
# Snapshot a previous real directory OR symlink target, so rollback is not tied
# to a checkout that may itself be updated after this installation.
if [[ -e "$root/app" || -L "$root/app" ]]; then
  [[ -d "$root/app" ]] || fail PREVIOUS_APP_INVALID
  backup=$(mktemp -d "$root/rollback/p01.XXXXXXXX")
  chmod 0755 "$backup"
  cp -aL "$root/app/." "$backup/"
fi
next="$root/.app-next-$$"
ln -s "$release" "$next"
if [[ -L "$root/app" ]]; then
  mv -Tf "$next" "$root/app"
elif [[ -d "$root/app" ]]; then
  old="$root/.app-previous-$$"
  mv "$root/app" "$old"
  if mv -T "$next" "$root/app"; then
    rm -rf "$old"
  else
    mv "$old" "$root/app"
    exit 1
  fi
else
  mv -T "$next" "$root/app"
fi
printf '%s\n' 'P01_CODE_STAGED=PASS'
