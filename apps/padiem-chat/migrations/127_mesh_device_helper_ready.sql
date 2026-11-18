-- #7987: the latest user-session helper readiness the executor observed on each
-- linked PC, owned by the COM2 Mesh queue. It is display evidence only: this
-- table never grants, blocks or schedules a PC command, and it holds no user
-- name, path or secret - five closed values and the queue's own receipt time.
CREATE TABLE IF NOT EXISTS mesh_device_helper_ready (
  device_id TEXT PRIMARY KEY CHECK(length(device_id) BETWEEN 1 AND 256),
  state_json TEXT NOT NULL,
  received_at TEXT NOT NULL
);
