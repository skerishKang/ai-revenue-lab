from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from kagent.connector_trust import ConnectorWriteIntent
from kagent.contracts import ContractError
from kagent.postgres_connector import (
    FUNCTION_EXECUTE_ALLOWLIST_REQUIRED,
    GENERIC_DDL_MUTATION_SUPPORTED,
    GENERIC_PRIVILEGE_MUTATION_SUPPORTED,
    LEAST_PRIVILEGE_ROLE_REQUIRED,
    RAW_POSTGRES_DSN_IN_B54,
    REAL_POSTGRES_CONNECTION_CONFIGURED,
    SERVER_SIDE_READ_ONLY_TRANSACTION_REQUIRED,
    STATEMENT_TIMEOUT_REQUIRED,
    PostgresBindingProjection,
    PostgresMutationApproval,
    PostgresQueryBudget,
    PostgresQueryResult,
    PostgresReadKind,
    PostgresReadRequest,
    UnconfiguredPostgresReadPort,
    classify_postgres_read_sql,
)

NOW = datetime(2026, 9, 3, 7, 20, tzinfo=timezone.utc)


class PostgresSqlClassifierTests(unittest.TestCase):
    def test_plain_select_cte_and_explain_are_allowed(self):
        self.assertEqual(classify_postgres_read_sql("SELECT id FROM users LIMIT 10").kind, PostgresReadKind.SELECT)
        self.assertEqual(
            classify_postgres_read_sql("WITH recent AS (SELECT id FROM users) SELECT id FROM recent").kind,
            PostgresReadKind.SELECT,
        )
        self.assertEqual(
            classify_postgres_read_sql("EXPLAIN (FORMAT JSON) SELECT id FROM users").kind,
            PostgresReadKind.EXPLAIN,
        )

    def test_one_trailing_semicolon_is_allowed_but_multiple_statements_are_not(self):
        classify_postgres_read_sql("SELECT 1;")
        for sql in (
            "SELECT 1; SELECT 2",
            "SELECT 1; DROP TABLE users;",
            "SELECT 1;;",
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(ContractError):
                    classify_postgres_read_sql(sql)

    def test_semicolons_and_keywords_inside_literals_comments_and_dollar_quotes_do_not_escape(self):
        safe = (
            "SELECT 'DROP TABLE x; UPDATE y SET a=1' AS txt",
            "SELECT $$; DELETE FROM users;$$ AS txt",
            "SELECT 1 /* DROP TABLE x; /* nested */ UPDATE y */",
            "SELECT 1 -- DELETE FROM users;\n",
        )
        for sql in safe:
            with self.subTest(sql=sql):
                classify_postgres_read_sql(sql)

    def test_dml_ddl_privilege_admin_and_session_commands_are_rejected(self):
        blocked = (
            "INSERT INTO t(id) VALUES (1)",
            "WITH x AS (DELETE FROM t RETURNING id) SELECT * FROM x",
            "UPDATE t SET a=1 RETURNING *",
            "DELETE FROM t",
            "MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE",
            "CREATE TEMP TABLE x(id int)",
            "ALTER TABLE t ADD COLUMN x int",
            "DROP TABLE t",
            "TRUNCATE t",
            "GRANT SELECT ON t TO role1",
            "REVOKE SELECT ON t FROM role1",
            "COPY t TO '/tmp/x'",
            "CALL dangerous()",
            "DO $$ BEGIN RAISE NOTICE 'x'; END $$",
            "SET statement_timeout = 0",
            "RESET ALL",
            "VACUUM t",
            "ANALYZE t",
            "LOCK TABLE t",
            "LISTEN channel1",
            "NOTIFY channel1",
        )
        for sql in blocked:
            with self.subTest(sql=sql):
                with self.assertRaises(ContractError):
                    classify_postgres_read_sql(sql)

    def test_row_locking_selects_are_rejected(self):
        for suffix in ("FOR UPDATE", "FOR SHARE", "FOR NO KEY UPDATE", "FOR KEY SHARE"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ContractError):
                    classify_postgres_read_sql(f"SELECT * FROM t {suffix}")

    def test_known_side_effect_functions_are_rejected_even_inside_select(self):
        for expression in (
            "nextval('seq')",
            "setval('seq', 2)",
            "pg_notify('x','y')",
            "pg_catalog.pg_terminate_backend(123)",
            "set_config('transaction_read_only','off',false)",
            "lo_export(1, '/tmp/x')",
            "pg_advisory_lock(1)",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(ContractError):
                    classify_postgres_read_sql(f"SELECT {expression}")

    def test_explain_analyze_is_rejected(self):
        with self.assertRaises(ContractError):
            classify_postgres_read_sql("EXPLAIN ANALYZE SELECT * FROM users")

    def test_unterminated_comments_and_literals_fail_closed(self):
        for sql in ("SELECT 'x", "SELECT $$x", "SELECT 1 /* x"):
            with self.subTest(sql=sql):
                with self.assertRaises(ContractError):
                    classify_postgres_read_sql(sql)


class PostgresContractTests(unittest.TestCase):
    def binding(self) -> PostgresBindingProjection:
        return PostgresBindingProjection(
            binding_ref="pg_binding_1",
            workspace_ref="workspace_1",
            project_ref="neon_project_1",
            branch_ref="neon_branch_1",
            database_ref="appdb",
            role_ref="padiem_readonly",
            allowed_schemas=("public",),
        )

    def test_binding_projection_is_secret_free_and_requires_least_privilege(self):
        rendered = self.binding().safe_dict()
        self.assertFalse(rendered["raw_dsn"])
        self.assertFalse(rendered["raw_password"])
        self.assertTrue(rendered["tls_required"])
        self.assertTrue(rendered["least_privilege_read_role"])
        self.assertTrue(rendered["function_execute_allowlist_required"])
        with self.assertRaises(ContractError):
            PostgresBindingProjection(
                binding_ref="pg_binding_1",
                workspace_ref="workspace_1",
                project_ref="project_1",
                branch_ref="branch_1",
                database_ref="appdb",
                role_ref="owner",
                allowed_schemas=("public",),
                least_privilege_read_role=False,
            )

    def test_request_reclassifies_sql_and_hides_parameters(self):
        request = PostgresReadRequest(
            binding_ref="pg_binding_1",
            workspace_ref="workspace_1",
            sql="SELECT id FROM users WHERE email = %s",
            parameters=("person@example.com",),
            budget=PostgresQueryBudget(max_rows=25, max_bytes=50_000, statement_timeout_ms=2_000),
            requested_at=NOW,
            schema_scope=("public",),
        )
        rendered = request.safe_dict()
        self.assertEqual(rendered["parameter_count"], 1)
        self.assertFalse(rendered["sql_text_present"])
        self.assertFalse(rendered["parameter_values_present"])
        self.assertEqual(rendered["max_rows"], 25)

    def test_query_result_requires_server_read_only_and_timeout_evidence(self):
        good = PostgresQueryResult(
            query_ref="query_1",
            columns=("id", "email"),
            rows=((1, "person@example.com"),),
            total_rows_observed=1,
            total_bytes_observed=64,
            truncated=False,
            masked_columns=("email",),
            transaction_read_only=True,
            statement_timeout_applied=True,
        )
        rendered = good.safe_dict()
        self.assertFalse(rendered["result_trusted_instruction"])
        self.assertTrue(rendered["transaction_read_only"])
        for kwargs in (
            {"transaction_read_only": False, "statement_timeout_applied": True},
            {"transaction_read_only": True, "statement_timeout_applied": False},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ContractError):
                    PostgresQueryResult(
                        query_ref="query_2",
                        columns=("id",),
                        rows=((1,),),
                        total_rows_observed=1,
                        total_bytes_observed=8,
                        truncated=False,
                        masked_columns=(),
                        **kwargs,
                    )

    def test_unconfigured_live_port_fails_closed(self):
        port = UnconfiguredPostgresReadPort()
        request = PostgresReadRequest(
            binding_ref="pg_binding_1",
            workspace_ref="workspace_1",
            sql="SELECT 1 AS id",
            parameters=(),
            budget=PostgresQueryBudget(),
            requested_at=NOW,
            schema_scope=("public",),
        )
        with self.assertRaises(ContractError):
            port.execute_read(binding=self.binding(), request=request)

    def test_mutation_requires_postgres_intent_row_guard_transaction_and_rollback_plan(self):
        payload = hashlib.sha256(b"UPDATE public.users SET active=false WHERE id=$1").hexdigest()
        intent = ConnectorWriteIntent(
            connector_id="postgres",
            binding_ref="pg_binding_1",
            actor_ref="actor_1",
            tool_name="update_rows",
            target_ref="appdb.public.users",
            payload_fingerprint=payload,
            idempotency_key="idem_1",
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            requested_at=NOW,
            expected_version_ref="snapshot_1",
        )
        approval = PostgresMutationApproval(
            intent=intent,
            database_ref="appdb",
            schema_ref="public",
            relation_ref="users",
            max_affected_rows=1,
            rollback_plan_ref="rollback_1",
        )
        rendered = approval.safe_dict()
        self.assertEqual(rendered["max_affected_rows"], 1)
        self.assertTrue(rendered["rollback_evidence_required"])
        self.assertFalse(rendered["generic_ddl_authority"])
        self.assertFalse(rendered["generic_privilege_authority"])
        with self.assertRaises(ContractError):
            PostgresMutationApproval(
                intent=intent,
                database_ref="appdb",
                schema_ref="public",
                relation_ref="users",
                max_affected_rows=1,
                rollback_plan_ref="rollback_1",
                transaction_required=False,
            )

    def test_nonclaims_are_explicit(self):
        self.assertFalse(RAW_POSTGRES_DSN_IN_B54)
        self.assertFalse(REAL_POSTGRES_CONNECTION_CONFIGURED)
        self.assertTrue(SERVER_SIDE_READ_ONLY_TRANSACTION_REQUIRED)
        self.assertTrue(STATEMENT_TIMEOUT_REQUIRED)
        self.assertTrue(LEAST_PRIVILEGE_ROLE_REQUIRED)
        self.assertTrue(FUNCTION_EXECUTE_ALLOWLIST_REQUIRED)
        self.assertFalse(GENERIC_DDL_MUTATION_SUPPORTED)
        self.assertFalse(GENERIC_PRIVILEGE_MUTATION_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
