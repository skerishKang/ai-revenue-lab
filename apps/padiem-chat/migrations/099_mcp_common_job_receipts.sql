-- Bind a common Claw dispatch receipt to its MCP token without creating a
-- second job store. Only the SHA-256 of dsp_<32hex> is retained here.
ALTER TABLE padiem_mcp_audit ADD COLUMN job_receipt_sha256 TEXT;
CREATE INDEX IF NOT EXISTS idx_mcp_audit_job_receipt_owner
    ON padiem_mcp_audit(user_id, token_id, device_id, job_receipt_sha256)
    WHERE job_receipt_sha256 IS NOT NULL;
