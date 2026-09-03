from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.postgres_connector import (
    PostgresBindingProjection,
    PostgresQueryBudget,
    PostgresQueryResult,
    PostgresReadRequest,
    classify_postgres_read_sql,
    validate_postgres_read_request,
)

NOW = datetime(2026, 9, 3, 7, 20, tzinfo=timezone.utc)


class PostgresConnectorHardeningTests(unittest.TestCase):
    def test_with_must_have_top_level_select_not_only_select_inside_cte(self):
        with self.assertRaises(ContractError):
            classify_postgres_read_sql("WITH x AS (SELECT 1) VALUES (1)")

    def test_quoted_builtin_side_effect_function_name_is_still_rejected(self):
        with self.assertRaises(ContractError):
            classify_postgres_read_sql('SELECT "nextval"(\'seq\')')
        with self.assertRaises(ContractError):
            classify_postgres_read_sql('SELECT pg_catalog."pg_notify"(\'a\',\'b\')')

    def test_negative_observed_counts_are_invalid(self):
        with self.assertRaises(ContractError):
            PostgresQueryResult(
                query_ref="query_1",
                columns=("id",),
                rows=(),
                total_rows_observed=-1,
                total_bytes_observed=0,
                truncated=False,
                masked_columns=(),
                transaction_read_only=True,
                statement_timeout_applied=True,
            )

    def test_empty_result_counts_are_valid(self):
        result = PostgresQueryResult(
            query_ref="query_2",
            columns=("id",),
            rows=(),
            total_rows_observed=0,
            total_bytes_observed=0,
            truncated=False,
            masked_columns=(),
            transaction_read_only=True,
            statement_timeout_applied=True,
        )
        self.assertEqual(result.total_rows_observed, 0)

    def test_binding_workspace_and_schema_scope_must_match_exact_trusted_binding(self):
        binding = PostgresBindingProjection(
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            project_ref="project_1",
            branch_ref="branch_1",
            database_ref="appdb",
            role_ref="readonly",
            allowed_schemas=("public", "reporting"),
        )
        request = PostgresReadRequest(
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            sql="SELECT 1 AS id",
            parameters=(),
            budget=PostgresQueryBudget(),
            requested_at=NOW,
            schema_scope=("public",),
        )
        validate_postgres_read_request(binding, request)

        mismatches = (
            PostgresReadRequest(
                binding_ref="binding_2",
                workspace_ref="workspace_1",
                sql="SELECT 1",
                parameters=(),
                budget=PostgresQueryBudget(),
                requested_at=NOW,
                schema_scope=("public",),
            ),
            PostgresReadRequest(
                binding_ref="binding_1",
                workspace_ref="workspace_2",
                sql="SELECT 1",
                parameters=(),
                budget=PostgresQueryBudget(),
                requested_at=NOW,
                schema_scope=("public",),
            ),
            PostgresReadRequest(
                binding_ref="binding_1",
                workspace_ref="workspace_1",
                sql="SELECT 1",
                parameters=(),
                budget=PostgresQueryBudget(),
                requested_at=NOW,
                schema_scope=("private",),
            ),
        )
        for bad in mismatches:
            with self.subTest(bad=bad.safe_dict()):
                with self.assertRaises(ContractError):
                    validate_postgres_read_request(binding, bad)


if __name__ == "__main__":
    unittest.main()
