-- Migration 005: durable episode-number reservations.
--
-- A MAX(episode_number)+1 read followed by COMMIT does not reserve the value;
-- two provider requests can therefore receive the same number before either
-- episode is inserted. This sequence table is advanced inside BEGIN IMMEDIATE
-- and makes allocation durable across connections and process restarts.

CREATE TABLE IF NOT EXISTS episode_number_sequences (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    episode_type TEXT NOT NULL CHECK(episode_type IN ('canon', 'personal_branch')),
    next_episode_number INTEGER NOT NULL CHECK(next_episode_number >= 1),
    PRIMARY KEY (world_id, episode_type)
);

INSERT OR IGNORE INTO episode_number_sequences (
    world_id, episode_type, next_episode_number
)
SELECT world_id, episode_type, COALESCE(MAX(episode_number), 0) + 1
FROM episodes
GROUP BY world_id, episode_type;

PRAGMA user_version = 5;
