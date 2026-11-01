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
# The host loads these packages from the same immutable release as Engine.
for item in packages/padiem-ai-core/padiem_ai_core packages/padiem-control-plane/padiem_control_plane apps/korean-ai-code-agent/src/kagent; do
  [[ -f "$source_root/$item/__init__.py" ]] || fail SHARED_PACKAGE_MISSING
done
[[ -d "$root" ]] || fail APP_ROOT_MISSING
install -d -m 0755 "$root/releases" "$root/rollback"
release=$(mktemp -d "$root/releases/p01.XXXXXXXX")
chmod 0755 "$release"
for item in app clients ingress migrations asgi.py worker.py worker_identity.py; do
  cp -aL "$source_engine/$item" "$release/$item"
done
for item in packages/padiem-ai-core/padiem_ai_core packages/padiem-control-plane/padiem_control_plane apps/korean-ai-code-agent/src/kagent; do
  cp -aL "$source_root/$item" "$release/$(basename "$item")"
done
# install.sh uses umask 077 and the source may already contain 0600 files.
# This release is code only; do not change the separate env/data directories.
if [[ $EUID -eq 0 ]]; then
  chown -R root:root "$release"
fi
find "$release" -type d -exec chmod a+rx,go-w {} +
find "$release" -type f -exec chmod a+r,go-w {} +
[[ -f "$release/asgi.py" ]] || fail ASGI_ENTRY_MISSING
# Snapshot a previous real directory OR symlink target, so rollback is not tied
# to a checkout that may itself be updated after this installation.
backup=''
if [[ -e "$root/app" || -L "$root/app" ]]; then
  [[ -d "$root/app" ]] || fail PREVIOUS_APP_INVALID
  backup=$(mktemp -d "$root/rollback/p01.XXXXXXXX")
  chmod 0755 "$backup"
  # Follow ordinary links as before, but omit links back to an ancestor.
  # cp -aL aborts on cycles, including links in older real app directories.
  python3 - "$root/app" "$backup" <<'PY'
import errno, os, shutil, sys

def ignore_cycles(directory, names):
    ancestors = set()
    path = os.path.abspath(directory)
    while True:
        ancestors.add(os.path.realpath(path))
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    ignored = []
    for name in names:
        candidate = os.path.join(directory, name)
        if not os.path.islink(candidate):
            continue
        try:
            target = os.path.realpath(candidate, strict=True)
            if target in ancestors:
                ignored.append(name)
        except OSError as error:
            if error.errno == errno.ELOOP:
                ignored.append(name)
            else:
                raise
    return ignored

shutil.copytree(sys.argv[1], sys.argv[2], dirs_exist_ok=True, ignore=ignore_cycles)
PY
  # The snapshot is the only way back; it was copied from a tree that can carry
  # 0600 files, so give the rollback the same guarantee the release has.
  find "$backup" -type d -exec chmod a+rx,go-w {} +
  find "$backup" -type f -exec chmod a+r,go-w {} +
  if [[ $EUID -eq 0 ]]; then chown -R root:root "$backup"; fi
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
