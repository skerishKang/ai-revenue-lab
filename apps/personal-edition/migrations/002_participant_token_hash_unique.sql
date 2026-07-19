CREATE UNIQUE INDEX idx_participants_access_token_hash
    ON participants(access_token_hash);
