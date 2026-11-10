#!/usr/bin/env bash
# #7388 — operator-only restore of one owner-deleted conversation.
#
# There is no user-facing restore. Deleting a conversation marks it
# (conversations.deleted_at) and the product hides it immediately; the row, its
# messages and the R2 originals are kept for the retention window (default 30
# days) and then deleted by app.conversation_purge. This script clears the
# marker inside that window — nothing else, and never for a live row.
#
# Run it on the Chat host as the database owner:
#   runuser -u padiem-chat -- /opt/padiem/chat-com2/ops/restore_conversation.sh chat_<32 hex>
#
# Exit status: 0 restored · 3 not found · 4 not deleted · 5 window closed.
set -euo pipefail

APP_DIR="${PADIEM_CHAT_APP_DIR:-/opt/padiem/chat-com2}"
PYTHON="${PADIEM_CHAT_PYTHON:-$APP_DIR/venv/bin/python}"
if [[ ! -x $PYTHON ]]; then
  PYTHON="$(command -v python3 || command -v python)"
fi

cd "$APP_DIR"
exec "$PYTHON" -m app.conversation_restore "$@"
