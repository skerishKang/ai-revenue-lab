-- #7076c queue copy: pc_shell user-session delegation flag (default 0).
ALTER TABLE oracle_mesh_dispatch ADD COLUMN user_mode INTEGER NOT NULL DEFAULT 0;
