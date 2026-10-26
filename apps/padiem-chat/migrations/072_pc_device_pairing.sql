-- #5573 PC pairing: one owner links their own Windows PC, many-to-many.
--
-- Before this, "which PC may this account use" lived only in a deployment
-- ownership map the Owner edited by hand (`ORACLE_MESH_OWNERSHIP_MAP_ENV`,
-- read at oracle_mesh_read_return_routes.py:432-462), a row was pinned to one
-- `.txt` file, and its parent folder was the only approved root
-- (`_pc_files_approved_root`). An external beta user with their own PC had no
-- way in: the Mesh node existed after install, but nothing recorded that it
-- belonged to them.
--
-- Two additive tables. No existing table is rebuilt, no existing row is
-- rewritten, and `mesh_device_presence` keeps its meaning: this is the
-- identity link, that stays the liveness receipt.
--
-- `pc_pairing_codes` — one issued one-time pairing code. Only hashes are stored:
-- the code itself is a possession proof that travels to the installing PC, and
-- the derived install tag is what the PC stamps into the MeshCentral agent's
-- own name so the server can recognise the node it created. A code is single
-- use and short lived; expiry is a column, not a cron.
--
-- `pc_device_links` — the link R1 asks for: exactly one row per
-- (user_id, mesh_node_id). Roots are approved per link and stored in
-- `roots_json`, because one PC shared by two accounts must not share a folder
-- grant, and a revoked link must not be able to revoke the other one's roots.
-- The JSON is server-written and server-parsed; no request ever names this
-- table's user or node.
--
-- Additive only. Apply through the separately approved D1 migration gate
-- against the canonical PADIEM_CHAT_DB. Nothing here mints a credential, a
-- Broker registration or an execution grant: a link says whose PC it is, and
-- dispatch authorization stays where it is today.
CREATE TABLE IF NOT EXISTS pc_pairing_codes (
  code_id TEXT PRIMARY KEY CHECK(length(code_id) BETWEEN 1 AND 64),
  code_sha256 TEXT NOT NULL UNIQUE CHECK(length(code_sha256) = 64),
  tag_sha256 TEXT NOT NULL UNIQUE CHECK(length(tag_sha256) = 64),
  user_id TEXT NOT NULL CHECK(length(user_id) BETWEEN 1 AND 256),
  state TEXT NOT NULL CHECK(state IN ('pending','claimed','cancelled')),
  -- The node the claim named. Kept on the code row so a used code still
  -- records which node consumed it; the link is the authority, not this.
  mesh_node_id TEXT CHECK(mesh_node_id IS NULL OR length(mesh_node_id) BETWEEN 1 AND 256),
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  claimed_at TEXT,
  CHECK(expires_at > issued_at)
);

CREATE INDEX IF NOT EXISTS idx_pc_pairing_codes_state_expiry
ON pc_pairing_codes (state, expires_at);

CREATE TABLE IF NOT EXISTS pc_device_links (
  link_id TEXT PRIMARY KEY CHECK(length(link_id) BETWEEN 1 AND 64),
  user_id TEXT NOT NULL CHECK(length(user_id) BETWEEN 1 AND 256),
  -- The composed MeshCentral identity only (`node/<domain>/<node>`); the bare
  -- form is refused, so a link can never name a device the Mesh lane cannot
  -- address. Validated again by the store on every write.
  mesh_node_id TEXT NOT NULL CHECK(length(mesh_node_id) BETWEEN 7 AND 256),
  label TEXT CHECK(label IS NULL OR length(label) BETWEEN 1 AND 128),
  state TEXT NOT NULL CHECK(state IN ('pending_verification','active','revoked')),
  roots_json TEXT NOT NULL DEFAULT '[]' CHECK(length(roots_json) <= 8192),
  pairing_code_id TEXT CHECK(pairing_code_id IS NULL OR length(pairing_code_id) BETWEEN 1 AND 64),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revoked_at TEXT,
  UNIQUE (user_id, mesh_node_id)
);

CREATE INDEX IF NOT EXISTS idx_pc_device_links_owner_state
ON pc_device_links (user_id, state);
