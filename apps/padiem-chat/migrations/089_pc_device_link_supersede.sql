-- #6694 (C) — the same physical computer may come back under a new Mesh node id
-- (agent reinstall, agent identity reset), which used to leave the old
-- `pc_device_links` row alive beside the new one: two rows, one computer. The
-- store now marks the older row for the same Windows computer name as
-- superseded the moment the newer claim lands.
--
-- Two additive columns, nothing rebuilt. `state` stays within the CHECK
-- vocabulary the table was created with ('revoked'), so every existing guard
-- (`link_for`, `links_for_owner`, `device_scope`, `list_active_device_ids`)
-- keeps dropping a superseded row without a new rule. `superseded_at` is what
-- distinguishes "the owner disconnected it" (revoked, columns NULL) from "the
-- same computer's newer link replaced it" (revoked + stamped). The public
-- projection names that second shape `replaced`, and the owner's list keeps
-- it so the record is never deleted behind their back.
--
-- Additive only. Apply through the approved D1 migration gate.
ALTER TABLE pc_device_links ADD COLUMN superseded_at TEXT;
ALTER TABLE pc_device_links ADD COLUMN superseded_by TEXT;
