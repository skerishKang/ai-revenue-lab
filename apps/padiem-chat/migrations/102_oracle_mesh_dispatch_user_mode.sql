-- #7076c: pc_shell user-session delegation flag (server-owned dispatch hint).
-- Default false preserves existing SYSTEM command execution path.
ALTER TABLE oracle_mesh_dispatch ADD COLUMN user_mode INTEGER NOT NULL DEFAULT 0;
