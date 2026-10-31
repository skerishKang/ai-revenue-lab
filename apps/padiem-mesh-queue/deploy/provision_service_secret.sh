#!/bin/bash
# #5881 follow-on — put one fresh secret on both sides of the Chat↔queue call.
#
# The value is generated here, written to a 0600 file on this host and handed to
# the caller's Cloudflare step on stdin. It is never printed, never echoed into a
# log and never committed: an operator reading this file learns the shape of the
# procedure and nothing about the value.
set -uo pipefail

umask 077
TARGET="${MESH_QUEUE_SERVICE_SECRET_FILE:-/opt/padiem/mesh-queue/service-secret.txt}"
[ -s "$TARGET" ] && { echo "MESH_QUEUE_SECRET=present file=$TARGET"; exit 0; }
mkdir -p "$(dirname "$TARGET")"
head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$TARGET"
chmod 600 "$TARGET"
echo "MESH_QUEUE_SECRET=created file=$TARGET bytes=$(wc -c < "$TARGET") mode=$(stat -c %a "$TARGET")"
cat <<'HOW'
Next, without printing the value: bind the same text on the Cloudflare side
(PC_QUEUE_SERVICE_SECRET) through the deploy gate, reading the file straight into
the request body - never as a shell argument, never echoed.
HOW
