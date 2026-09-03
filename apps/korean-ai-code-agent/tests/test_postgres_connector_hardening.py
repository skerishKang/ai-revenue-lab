from __future__ import annotations

import unittest

from kagent.contracts import ContractError
from kagent.postgres_connector import PostgresQueryResult, classify_postgres_read_sql


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


if __name__ == "__main__":
    unittest.main()
