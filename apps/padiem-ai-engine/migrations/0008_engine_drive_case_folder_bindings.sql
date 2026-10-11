-- #3188 (B67 Legal / Drive): durable Project -> selected Drive case-folder
-- binding for the Engine authority (app/drive_case_folder_binding.py).
--
-- One row per (workspace_ref, project_id, connector_id): a project has exactly
-- one active selected case folder per canonical Drive connection. Replacement is
-- an explicit upsert on this key, so an implicit multi-folder widening is not
-- representable. Identifier columns only: no credential material, no contact
-- addresses, no Drive content and no folder names are stored here.
--
-- Source migration only; applying it to any environment is a separate release
-- action (D1 provision gate). No Worker route, composition wiring or activation
-- lives here.

CREATE TABLE IF NOT EXISTS padiem_engine_drive_case_folder_bindings (
  workspace_ref TEXT NOT NULL CHECK (length(workspace_ref) > 0 AND length(workspace_ref) <= 128),
  project_id TEXT NOT NULL CHECK (project_id LIKE 'proj_%' AND length(project_id) = 37),
  connector_id TEXT NOT NULL CHECK (length(connector_id) > 0 AND length(connector_id) <= 128),
  drive_binding_ref TEXT NOT NULL CHECK (length(drive_binding_ref) > 0 AND length(drive_binding_ref) <= 128),
  selected_folder_id TEXT NOT NULL CHECK (length(selected_folder_id) > 0 AND length(selected_folder_id) <= 128),
  shared_drive_id TEXT CHECK (
    shared_drive_id IS NULL OR (length(shared_drive_id) > 0 AND length(shared_drive_id) <= 128)
  ),
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (workspace_ref, project_id, connector_id)
);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_drive_case_folder_bindings_active
  ON padiem_engine_drive_case_folder_bindings (workspace_ref, project_id, connector_id, active);
