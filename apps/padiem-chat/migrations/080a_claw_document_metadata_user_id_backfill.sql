WITH RECURSIVE parts(document_id, n, part, rest) AS (
  SELECT document_id, 0, '', object_key || '/'
  FROM claw_document_metadata
  UNION ALL
  SELECT document_id, n + 1, substr(rest, 1, instr(rest, '/') - 1),
         substr(rest, instr(rest, '/') + 1)
  FROM parts WHERE rest <> ''
), paths AS (
  SELECT document_id, max(n) AS depth,
         max(CASE WHEN n=1 THEN part END) AS root,
         max(CASE WHEN n=2 THEN part END) AS tenant,
         max(CASE WHEN n=3 THEN part END) AS product,
         max(CASE WHEN n=4 THEN part END) AS kind,
         max(CASE WHEN n=5 THEN part END) AS owner,
         max(CASE WHEN n=6 THEN part END) AS workspace,
         max(CASE WHEN n=7 THEN part END) AS p7,
         max(CASE WHEN n=8 THEN part END) AS p8,
         max(CASE WHEN n=9 THEN part END) AS p9,
         max(CASE WHEN n=10 THEN part END) AS p10,
         max(CASE WHEN n=11 THEN part END) AS p11
  FROM parts GROUP BY document_id
), candidates AS (
  SELECT m.document_id, p.owner AS user_id
  FROM claw_document_metadata m
  JOIN paths p ON p.document_id=m.document_id
  JOIN users u ON u.id=p.owner
  WHERE p.root='workspaces' AND p.product='claw'
    AND p.tenant=m.tenant_id AND p.workspace=m.tenant_id
    AND (
      (p.kind='web-office' AND p.depth=9 AND p.p7=m.document_id
       AND length(p.p8)=64 AND p.p8 NOT GLOB '*[^0-9a-f]*'
       AND p.p9=m.filename)
      OR (p.kind='web-office-workcopies' AND p.depth=10
       AND p.p9=m.document_id AND length(p.p10)=64
       AND p.p10 NOT GLOB '*[^0-9a-f]*')
      OR (p.kind='web-office-revisions' AND p.depth=11
       AND p.p10=m.document_id AND length(p.p11)=64
       AND p.p11 NOT GLOB '*[^0-9a-f]*')
    )
  UNION ALL
  SELECT m.document_id, r.user_id
  FROM claw_document_metadata m
  JOIN claw_run_history r ON r.artifact_document_id=m.document_id
  JOIN users u ON u.id=r.user_id
  WHERE r.user_id IS NOT NULL AND trim(r.user_id)<>''
), resolved AS (
  SELECT document_id, min(user_id) AS user_id FROM candidates
  GROUP BY document_id HAVING count(DISTINCT user_id)=1
)
UPDATE claw_document_metadata AS m
SET user_id=(
  SELECT x.user_id FROM resolved x WHERE x.document_id=m.document_id
)
WHERE (m.user_id IS NULL OR trim(m.user_id)='')
  AND EXISTS (
    SELECT 1 FROM resolved x WHERE x.document_id=m.document_id
  )
  AND NOT EXISTS (
    SELECT 1
    FROM claw_run_history r
    JOIN resolved x ON x.document_id=m.document_id
    WHERE r.artifact_document_id=m.document_id
      AND r.user_id IS NOT x.user_id
  )
  AND NOT EXISTS (
    SELECT 1
    FROM claw_conversation_artifact_index i
    JOIN resolved x ON x.document_id=m.document_id
    WHERE i.artifact_id=m.document_id
      AND (
        i.user_id IS NOT x.user_id
        OR i.workspace_ref IS NOT m.tenant_id
        OR i.location_ref IS NOT m.object_key
      )
  );
