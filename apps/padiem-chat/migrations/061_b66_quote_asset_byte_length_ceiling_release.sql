-- #4379: the B66 quote asset carries no PADIEM byte total. The 256 KiB upper
-- bound in 022 was a product-side capacity claim, not a platform request limit
-- or a Provider limit, so it is released here rather than enlarged. The
-- released migration is not rewritten: this forward migration rebuilds the
-- table, because SQLite cannot alter a CHECK constraint in place. The non-empty
-- lower bound and every other column, constraint, index and foreign key are
-- carried over unchanged. Source migration only: applying it to any environment
-- is a separate release action.
PRAGMA foreign_keys=OFF;
PRAGMA defer_foreign_keys=ON;

-- 022 b66_quote_asset: byte_length keeps `>= 1` and loses the 256 KiB bound.
CREATE TABLE b66_quote_asset_next (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    asset_kind TEXT NOT NULL CHECK (asset_kind IN ('logo', 'stamp')),
    media_type TEXT NOT NULL CHECK (media_type IN ('image/png', 'image/jpeg', 'image/webp')),
    object_key TEXT NOT NULL UNIQUE,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 1),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('approved', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO b66_quote_asset_next
  (id,user_id,workspace_id,asset_kind,media_type,object_key,byte_length,sha256,status,created_at,updated_at)
SELECT id,user_id,workspace_id,asset_kind,media_type,object_key,byte_length,sha256,status,created_at,updated_at
FROM b66_quote_asset;

DROP TABLE b66_quote_asset;
ALTER TABLE b66_quote_asset_next RENAME TO b66_quote_asset;

CREATE INDEX IF NOT EXISTS idx_b66_quote_asset_owner_workspace_status
ON b66_quote_asset (user_id, workspace_id, status, updated_at DESC);

PRAGMA foreign_keys=ON;
