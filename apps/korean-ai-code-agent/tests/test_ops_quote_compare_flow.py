"""#2812: the Claw manual-intake quote comparison flow must stay deterministic.

These tests pin the product boundary: the existing ``SupplierComparisonEngine``
does the deciding, captured fields are the only inputs, a missing field stays
UNKNOWN, and a negotiation never leaves the product.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import re
import unittest

from kagent.contracts import ContractError
from kagent.ops_comparison import (
    ComparisonMode,
    ComparisonWeights,
    NegotiationTarget,
    SupplierComparisonAnalysis,
    SupplierDecisionScore,
)
from kagent.ops_contracts import Money
from kagent.ops_quote_compare_flow import (
    EXTERNAL_SENDS,
    EXTERNAL_SEND_SUPPORTED,
    LLM_PRICE_INVENTION,
    MODEL_CALLS,
    NEGOTIATION_DRAFT_ONLY,
    NEGOTIATION_REASON_SINGLE_SUPPLIER,
    QUOTE_COMPARE_ERROR_CODES,
    OpsQuoteCompareFlowError,
    build_comparison_document,
    compare_supplier_quotes,
)

SOURCE = Path(__file__).resolve().parents[1] / "src" / "kagent" / "ops_quote_compare_flow.py"
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
AMOUNT_RE = re.compile(r"[0-9][0-9,]* [A-Z]{3}")


def supplier(
    supplier_id: str,
    total_minor: int,
    *,
    label: str | None = None,
    delivery: str | None = None,
    due_days: int | None = None,
    prepaid: bool = False,
    **extra: object,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "supplier_id": supplier_id,
        "supplier_label": label or supplier_id.upper(),
        "item_label": "산업용 랙",
        "total_minor": total_minor,
    }
    if delivery is not None:
        entry["promised_delivery_date"] = delivery
    if due_days is not None or prepaid:
        entry["payment_terms"] = {
            "label": "선입금" if prepaid else "월말매입",
            "due_days": due_days,
            "prepaid": prepaid,
        }
    entry.update(extra)
    return entry


def payload(*entries: dict[str, object], **top: object) -> dict[str, object]:
    body: dict[str, object] = {"suppliers": list(entries)}
    body.update(top)
    return body


A = supplier("supplier_a", 1200000, label="A업체", delivery="2026-10-05", due_days=30)
B = supplier("supplier_b", 1050000, label="B업체", delivery="2026-10-20", due_days=0, prepaid=True)
C = supplier("supplier_c", 1150000, label="C업체")
CAPTURED_AMOUNTS = {"1,200,000 KRW", "1,050,000 KRW", "1,150,000 KRW"}


class _RecordingEngine:
    """Stand-in that records what the flow asks the engine to decide."""

    def __init__(
        self,
        *,
        recommend: str = "supplier_a",
        evaluate_error: ContractError | None = None,
        negotiation_error: ContractError | None = None,
    ) -> None:
        self.recommend = recommend
        self.evaluate_error = evaluate_error
        self.negotiation_error = negotiation_error
        self.evaluate_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.negotiation_calls: list[dict[str, object]] = []

    def evaluate(self, quotes, *, mode=ComparisonMode.BALANCED, weights=None):
        self.evaluate_calls.append((quotes, {"mode": mode, "weights": weights}))
        if self.evaluate_error is not None:
            raise self.evaluate_error
        scores = tuple(
            SupplierDecisionScore(
                supplier_id=quote.supplier_id,
                quote_id=quote.quote_id,
                quote_version=quote.version,
                total=quote.total,
                promised_delivery_date=quote.promised_delivery_date,
                due_days=quote.payment_terms.due_days if quote.payment_terms else None,
                prepaid=quote.payment_terms.prepaid if quote.payment_terms else None,
                price_rank=index + 1,
                delivery_rank=1 if quote.promised_delivery_date else None,
                cashflow_rank=None,
                score_basis_points=10000 - index,
                unknown_fields=() if quote.promised_delivery_date else ("promised_delivery_date",),
            )
            for index, quote in enumerate(quotes)
        )
        return SupplierComparisonAnalysis(
            mode=mode,
            weights=weights or ComparisonWeights(),
            scores=scores,
            recommended_supplier_id=self.recommend,
            reason_codes=("deterministic_stub",),
        )

    def negotiation_target_from_competing_quote(self, *, target_quote, competing_quotes):
        self.negotiation_calls.append({"target": target_quote, "competing": competing_quotes})
        if self.negotiation_error is not None:
            raise self.negotiation_error
        best = min(
            (quote for quote in competing_quotes if quote.supplier_id != target_quote.supplier_id),
            key=lambda quote: quote.total.amount_minor,
        )
        return NegotiationTarget(
            supplier_id=target_quote.supplier_id,
            quote_id=target_quote.quote_id,
            quote_version=target_quote.version,
            current_total=target_quote.total,
            target_total=Money(best.total.amount_minor, best.total.currency),
            basis=f"captured_competing_quote:{best.quote_id}:v{best.version}",
        )


class DeterministicComparisonTests(unittest.TestCase):
    def test_same_input_projects_identical_result(self):
        first = compare_supplier_quotes(payload(A, B, C), received_at=NOW).safe_dict()
        second = compare_supplier_quotes(payload(A, B, C), received_at=NOW).safe_dict()
        self.assertEqual(first, second)

    def test_lowest_price_mode_selects_the_cheaper_captured_quote(self):
        outcome = compare_supplier_quotes(payload(A, B, mode="lowest_price"), received_at=NOW)
        self.assertEqual(outcome.recommended_supplier_id, "supplier_b")
        self.assertEqual(outcome.score_for("supplier_b").price_rank, 1)

    def test_fastest_delivery_mode_selects_the_earliest_promised_date(self):
        outcome = compare_supplier_quotes(payload(A, B, mode="fastest_delivery"), received_at=NOW)
        self.assertEqual(outcome.recommended_supplier_id, "supplier_a")

    def test_best_cashflow_mode_prefers_longer_nonprepaid_terms(self):
        slow_payment = supplier("supplier_d", 1300000, delivery="2026-10-01", due_days=60)
        outcome = compare_supplier_quotes(
            payload(B, slow_payment, mode="best_cashflow_fit"), received_at=NOW
        )
        self.assertEqual(outcome.recommended_supplier_id, "supplier_d")

    def test_balanced_mode_honours_declared_weights(self):
        default = compare_supplier_quotes(payload(A, B, C), received_at=NOW)
        self.assertEqual(default.weights, ComparisonWeights(50, 25, 25))
        price_only = compare_supplier_quotes(
            payload(A, B, C, weights={"price": 100, "delivery": 0, "cashflow": 0}),
            received_at=NOW,
        )
        self.assertEqual(price_only.weights, ComparisonWeights(100, 0, 0))
        self.assertEqual(
            price_only.recommended_supplier_id,
            compare_supplier_quotes(payload(A, B, C, mode="lowest_price"), received_at=NOW).recommended_supplier_id,
        )
        # A is dearer but wins on delivery and cashflow, so a pure-price weight
        # must rank C above A while the default weight ranks A above C.
        self.assertGreater(
            default.score_for("supplier_a").score_basis_points,
            default.score_for("supplier_c").score_basis_points,
        )
        self.assertLess(
            price_only.score_for("supplier_a").score_basis_points,
            price_only.score_for("supplier_c").score_basis_points,
        )
        delivery_heavy = compare_supplier_quotes(
            payload(A, B, C, weights={"price": 0, "delivery": 100, "cashflow": 0}),
            received_at=NOW,
        )
        self.assertEqual(delivery_heavy.recommended_supplier_id, "supplier_a")
        cashflow_heavy = compare_supplier_quotes(
            payload(A, B, C, weights={"price": 0, "delivery": 0, "cashflow": 100}),
            received_at=NOW,
        )
        self.assertEqual(cashflow_heavy.recommended_supplier_id, "supplier_a")

    def test_four_declared_modes_are_the_supported_surface(self):
        for mode in ComparisonMode:
            outcome = compare_supplier_quotes(payload(A, B, C, mode=mode.value), received_at=NOW)
            self.assertEqual(outcome.mode, mode)
        with self.assertRaises(OpsQuoteCompareFlowError) as caught:
            compare_supplier_quotes(payload(A, B, mode="llm_best_guess"), received_at=NOW)
        self.assertEqual(caught.exception.error_code, "invalid_comparison_mode")

    def test_missing_fields_stay_unknown_and_are_never_filled_in(self):
        outcome = compare_supplier_quotes(payload(A, C), received_at=NOW)
        score = outcome.score_for("supplier_c")
        self.assertIsNone(score.delivery_rank)
        self.assertIsNone(score.cashflow_rank)
        self.assertEqual(score.unknown_fields, ("promised_delivery_date", "payment_terms"))
        projection = next(
            item
            for item in outcome.safe_dict()["suppliers"]
            if item["supplier_id"] == "supplier_c"
        )
        self.assertIsNone(projection["promised_delivery_date"])
        self.assertEqual(projection["payment_terms_label"], "")
        self.assertIsNone(projection["due_days"])
        self.assertIsNone(projection["prepaid"])
        document = build_comparison_document(outcome)
        self.assertIn("미확인", document)
        self.assertIn("promised_delivery_date", document)

    def test_evidence_reference_and_digest_survive_into_the_projection(self):
        entry = supplier(
            "supplier_e",
            900000,
            evidence_ref="E업체 견적서 2026-09-18",
            evidence_sha256="A" * 64,
        )
        outcome = compare_supplier_quotes(payload(entry), received_at=NOW)
        quote = outcome.quote_for("supplier_e")
        assert quote.source_artifact is not None
        self.assertEqual(quote.source_artifact.display_name, "E업체 견적서 2026-09-18")
        self.assertEqual(quote.source_artifact.content_sha256, "a" * 64)
        self.assertEqual(quote.source_artifact.kind, "claw_manual_quote_evidence")
        self.assertEqual(quote.rfq_id, "rfq_manual_supplier_e")
        self.assertEqual(quote.status.value, "received")
        self.assertEqual(
            outcome.safe_dict()["suppliers"][0]["evidence_ref"], "E업체 견적서 2026-09-18"
        )

    def test_projection_is_bounded_and_product_safe(self):
        projection = compare_supplier_quotes(payload(A, B, C), received_at=NOW).safe_dict()
        self.assertEqual(projection["supplier_count"], 3)
        self.assertEqual(projection["currency"], "KRW")
        self.assertEqual(projection["weights"], {"price": 50, "delivery": 25, "cashflow": 25})
        self.assertIs(projection["advisory_only"], True)
        self.assertNotIn("raw_content", projection)
        self.assertNotIn("received_at", projection)
        self.assertEqual(
            {item["supplier_id"] for item in projection["suppliers"]},
            {"supplier_a", "supplier_b", "supplier_c"},
        )


class NegotiationDraftTests(unittest.TestCase):
    def test_negotiation_target_comes_from_a_captured_competing_quote(self):
        outcome = compare_supplier_quotes(payload(A, B, C), received_at=NOW)
        target = outcome.negotiation_target
        assert target is not None and outcome.negotiation is not None
        self.assertEqual(target.supplier_id, "supplier_a")
        self.assertEqual(target.current_total.amount_minor, 1200000)
        self.assertEqual(target.target_total.amount_minor, 1050000)
        self.assertEqual(target.basis, "captured_competing_quote:quote_supplier_b:v1")
        self.assertEqual(outcome.negotiation.target_total, target.target_total)
        self.assertEqual(outcome.negotiation.quote_version, 1)
        self.assertEqual(outcome.negotiation.supplier_id, "supplier_a")

    def test_negotiation_message_only_restates_captured_amounts(self):
        outcome = compare_supplier_quotes(payload(A, B, C), received_at=NOW)
        assert outcome.negotiation is not None
        message = outcome.negotiation.message
        self.assertIn("captured_competing_quote:quote_supplier_b:v1", message)
        self.assertIn("2026-10-05", message)
        self.assertIn("DRAFT ONLY", message)
        self.assertLessEqual(len(message), 4000)
        self.assertTrue(set(AMOUNT_RE.findall(message)) <= CAPTURED_AMOUNTS)
        self.assertEqual(
            set(AMOUNT_RE.findall(message)), {"1,200,000 KRW", "1,050,000 KRW"}
        )

    def test_projection_declares_draft_only_and_zero_sends(self):
        projection = compare_supplier_quotes(payload(A, B, C), received_at=NOW).safe_dict()
        negotiation = projection["negotiation"]
        self.assertIsNotNone(negotiation)
        self.assertEqual(negotiation["status"], "draft_only")
        self.assertIs(negotiation["send_performed"], False)
        self.assertIs(projection["draft_only"], True)
        self.assertIs(projection["external_send_supported"], False)
        self.assertEqual(projection["external_sends"], 0)
        self.assertEqual(projection["model_calls"], 0)
        self.assertEqual(EXTERNAL_SENDS, 0)
        self.assertIs(EXTERNAL_SEND_SUPPORTED, False)
        self.assertIs(LLM_PRICE_INVENTION, False)
        self.assertIs(NEGOTIATION_DRAFT_ONLY, True)
        self.assertEqual(MODEL_CALLS, 0)

    def test_single_supplier_is_safe_and_refuses_to_invent_a_target(self):
        outcome = compare_supplier_quotes(payload(A), received_at=NOW)
        self.assertEqual(outcome.recommended_supplier_id, "supplier_a")
        self.assertIsNone(outcome.negotiation)
        self.assertIsNone(outcome.negotiation_target)
        self.assertEqual(outcome.negotiation_unavailable_reason, NEGOTIATION_REASON_SINGLE_SUPPLIER)
        projection = outcome.safe_dict()
        self.assertIsNone(projection["negotiation"])
        self.assertEqual(
            projection["negotiation_unavailable_reason"], NEGOTIATION_REASON_SINGLE_SUPPLIER
        )
        self.assertIn(NEGOTIATION_REASON_SINGLE_SUPPLIER, build_comparison_document(outcome))


class FlowDelegationTests(unittest.TestCase):
    """The engine decides: a flow that computed its own ranking fails these."""

    def test_comparison_is_delegated_to_the_injected_engine(self):
        engine = _RecordingEngine()
        compare_supplier_quotes(
            payload(A, B, mode="fastest_delivery"), received_at=NOW, engine=engine
        )
        self.assertEqual(len(engine.evaluate_calls), 1)
        quotes, kwargs = engine.evaluate_calls[0]
        self.assertEqual([quote.supplier_id for quote in quotes], ["supplier_a", "supplier_b"])
        self.assertEqual(kwargs["mode"], ComparisonMode.FASTEST_DELIVERY)
        self.assertEqual(len(engine.negotiation_calls), 1)

    def test_recommendation_follows_the_engine_not_flow_arithmetic(self):
        engine = _RecordingEngine(recommend="supplier_b")
        outcome = compare_supplier_quotes(payload(A, B, C), received_at=NOW, engine=engine)
        self.assertEqual(outcome.recommended_supplier_id, "supplier_b")
        self.assertEqual(outcome.analysis.reason_codes, ("deterministic_stub",))

    def test_engine_refusal_fails_closed_instead_of_falling_back(self):
        engine = _RecordingEngine(evaluate_error=ContractError("quotes must use one currency"))
        with self.assertRaises(OpsQuoteCompareFlowError) as caught:
            compare_supplier_quotes(payload(A, B), received_at=NOW, engine=engine)
        self.assertEqual(caught.exception.error_code, "comparison_unavailable")

    def test_negotiation_target_is_delegated_and_refusal_yields_no_draft(self):
        engine = _RecordingEngine(negotiation_error=ContractError("no competing quote"))
        outcome = compare_supplier_quotes(payload(A, B), received_at=NOW, engine=engine)
        self.assertEqual(len(engine.negotiation_calls), 1)
        self.assertIsNone(outcome.negotiation)
        self.assertEqual(outcome.negotiation_unavailable_reason, "no_same_currency_competing_quote")


class FailClosedInputTests(unittest.TestCase):
    def _code(self, body: dict[str, object]) -> str:
        with self.assertRaises(OpsQuoteCompareFlowError) as caught:
            compare_supplier_quotes(body, received_at=NOW)
        return caught.exception.error_code

    def test_empty_supplier_set_fails_closed(self):
        self.assertEqual(self._code({"suppliers": []}), "suppliers_required")
        self.assertEqual(self._code({"suppliers": "not-a-list"}), "suppliers_required")
        self.assertEqual(self._code({}), "suppliers_required")

    def test_non_object_payload_fails_closed(self):
        with self.assertRaises(OpsQuoteCompareFlowError) as caught:
            compare_supplier_quotes(["a"], received_at=NOW)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.error_code, "invalid_payload")

    def test_missing_price_fails_closed(self):
        entry = {"supplier_id": "supplier_x", "promised_delivery_date": "2026-10-01"}
        self.assertEqual(self._code(payload(entry)), "supplier_price_missing")

    def test_binary_float_money_fails_closed(self):
        self.assertEqual(
            self._code(payload({"supplier_id": "supplier_x", "total_minor": 1.5})), "invalid_price"
        )
        self.assertEqual(
            self._code(payload({"supplier_id": "supplier_x", "unit_price_minor": 1e3})),
            "invalid_price",
        )

    def test_zero_and_negative_totals_fail_closed(self):
        self.assertEqual(self._code(payload(supplier("s1", 0))), "supplier_total_must_be_positive")
        self.assertEqual(
            self._code(payload(supplier("s1", -500))), "supplier_total_must_be_positive"
        )

    def test_captured_total_must_match_quantity_times_unit_price(self):
        mismatched = {
            "supplier_id": "supplier_x",
            "quantity": "10",
            "unit_price_minor": 100000,
            "total_minor": 1000001,
        }
        self.assertEqual(self._code(payload(mismatched)), "supplier_line_total_mismatch")
        consistent = {
            "supplier_id": "supplier_x",
            "quantity": "10",
            "unit_price_minor": 100000,
            "total_minor": 1000000,
        }
        outcome = compare_supplier_quotes(payload(consistent), received_at=NOW)
        self.assertEqual(outcome.quotes[0].total.amount_minor, 1000000)
        self.assertEqual(outcome.quotes[0].lines[0].quantity, 10)

    def test_indivisible_total_without_unit_price_is_not_rounded(self):
        entry = {"supplier_id": "supplier_x", "quantity": "3", "total_minor": 1000000}
        self.assertEqual(self._code(payload(entry)), "supplier_unit_price_underivable")

    def test_fractional_minor_unit_line_fails_closed(self):
        entry = {"supplier_id": "supplier_x", "quantity": "0.5", "unit_price_minor": 100001}
        self.assertEqual(self._code(payload(entry)), "fractional_line_total")

    def test_lead_time_text_is_not_converted_into_a_delivery_date(self):
        self.assertEqual(
            self._code(payload(supplier("s1", 100, delivery="납기 2주"))), "invalid_delivery_date"
        )
        self.assertEqual(
            self._code(payload(supplier("s1", 100, delivery="2026-13-45"))),
            "invalid_delivery_date",
        )

    def test_malformed_quantity_payment_and_evidence_fail_closed(self):
        self.assertEqual(
            self._code(payload(supplier("s1", 100, quantity="many"))), "invalid_quantity"
        )
        self.assertEqual(
            self._code(payload(supplier("s1", 100, payment_terms="30일"))), "invalid_payment_terms"
        )
        self.assertEqual(
            self._code(payload(supplier("s1", 100, payment_terms={"due_days": "30"}))),
            "invalid_payment_terms",
        )
        self.assertEqual(
            self._code(
                payload(supplier("s1", 100, payment_terms={"label": "월말", "prepaid": "yes"}))
            ),
            "invalid_payment_terms",
        )
        self.assertEqual(
            self._code(payload(supplier("s1", 100, evidence_sha256="not-a-digest"))),
            "invalid_evidence_reference",
        )

    def test_cross_currency_duplicate_supplier_and_bad_identity_fail_closed(self):
        self.assertEqual(
            self._code(payload(supplier("s1", 100), supplier("s2", 200, currency="USD"))),
            "mixed_currency",
        )
        self.assertEqual(
            self._code(payload(supplier("s1", 100), supplier("s1", 200))), "invalid_supplier_id"
        )
        self.assertEqual(self._code(payload(supplier("s1", 100), currency="KR")), "invalid_currency")
        self.assertEqual(
            self._code(payload(supplier("s1", 100), workspace_id="ws" * 200)), "invalid_workspace_id"
        )
        self.assertEqual(self._code(payload("plain-string")), "invalid_supplier_entry")
        self.assertEqual(self._code(payload({"total_minor": 100})), "invalid_supplier_id")

    def test_weights_must_be_declared_integers_summing_to_100(self):
        self.assertEqual(
            self._code(payload(A, B, weights={"price": 50, "delivery": 20, "cashflow": 20})),
            "invalid_comparison_weights",
        )
        self.assertEqual(
            self._code(payload(A, B, weights={"price": "50"})), "invalid_comparison_weights"
        )

    def test_bounds_and_control_characters_fail_closed(self):
        self.assertEqual(
            self._code(payload(*[supplier(f"s{i}", 100 + i) for i in range(101)])),
            "too_many_suppliers",
        )
        self.assertEqual(
            self._code(payload(supplier("s1", 100, label="가" * 201))), "invalid_supplier_label"
        )
        self.assertEqual(
            self._code(payload(supplier("s1", 100, item_label="제어\x00문자"))),
            "invalid_item_label",
        )
        self.assertEqual(
            self._code(payload(supplier("s1", 10**18))), "invalid_price"
        )

    def test_error_vocabulary_is_closed(self):
        for code in QUOTE_COMPARE_ERROR_CODES:
            self.assertIsInstance(code, str)
        with self.assertRaises(ValueError):
            OpsQuoteCompareFlowError("not_a_declared_code", "message")


class DocumentBoundaryTests(unittest.TestCase):
    def test_document_is_reproducible_and_labels_every_captured_amount(self):
        outcome = compare_supplier_quotes(payload(A, B, C), received_at=NOW)
        first = build_comparison_document(outcome)
        self.assertEqual(first, build_comparison_document(outcome))
        for amount in CAPTURED_AMOUNTS:
            self.assertIn(amount, first)
        self.assertTrue(set(AMOUNT_RE.findall(first)) <= CAPTURED_AMOUNTS)
        for heading in ("## 비교 표", "## 한정된 추천", "## 항목별 우위", "## 협상 초안 (DRAFT ONLY)"):
            self.assertIn(heading, first)
        self.assertIn("모델 추론", first)
        self.assertIn("자동 발송되지 않", first)

    def test_document_names_the_per_axis_winners_from_captured_ranks(self):
        document = build_comparison_document(compare_supplier_quotes(payload(A, B, C), received_at=NOW))
        self.assertIn("- 최저가: B업체", document)
        self.assertIn("- 최단 납기: A업체", document)
        self.assertIn("- 현금흐름 유리: A업체", document)

    def test_document_does_not_invent_a_winner_for_an_unknown_axis(self):
        outcome = compare_supplier_quotes(payload(supplier("s1", 500)), received_at=NOW)
        document = build_comparison_document(outcome)
        self.assertIn("- 최단 납기: 미확인", document)
        self.assertIn("- 현금흐름 유리: 미확인", document)


class ModuleBoundaryTests(unittest.TestCase):
    """Mutation guards: a provider import or an outbound send fails these."""

    def setUp(self) -> None:
        self.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    def _imported_modules(self) -> set[str]:
        modules: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules.update((node.module or "").partition(".")[0] for _ in node.names)
                modules.discard("")
        return modules

    def _relative_imports(self) -> set[str]:
        return {
            f"{'.' * node.level}{node.module or ''}"
            for node in ast.walk(self.tree)
            if isinstance(node, ast.ImportFrom) and node.level
        }

    def _called_attributes(self) -> set[str]:
        return {
            node.func.attr
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def _identifiers(self) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.keyword):
                names.add(node.arg or "")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
        return names

    def test_stdlib_imports_stay_inside_the_deterministic_boundary(self):
        self.assertEqual(
            self._imported_modules(),
            {"__future__", "dataclasses", "datetime", "decimal", "re", "typing"},
        )

    def test_only_the_existing_ops_authority_is_imported(self):
        self.assertEqual(
            self._relative_imports(),
            {".contracts", ".ops_comparison", ".ops_contracts", ".security"},
        )

    def test_no_outbound_send_is_ever_called(self):
        self.assertTrue(
            self._called_attributes().isdisjoint(
                {
                    "send_negotiation",
                    "send_rfq",
                    "send_purchase_order",
                    "issue_purchase_order",
                    "execute",
                    "dispatch",
                    "post",
                    "put",
                    "fetch",
                    "request",
                    "connect",
                    "write_bytes",
                    "write_text",
                }
            )
        )

    def test_no_provider_credential_or_connector_is_named(self):
        forbidden = {
            "P01CoreOrchestrationAdapter",
            "P01AdapterError",
            "create_claw_run",
            "PadiemTierB14Client",
            "ManualIntakeRouter",
            "OpsOutboundPort",
            "UnconfiguredOpsOutboundPort",
            "OutboundActionResult",
            "ApprovalProjection",
            "ApprovalAction",
            "PurchaseOrder",
            "httpx",
            "urlopen",
            "environ",
            "getenv",
            "api_key",
            "client_secret",
            "open",
            "migrate",
        }
        self.assertTrue(self._identifiers().isdisjoint(forbidden))

    def test_engine_and_contracts_are_reused_not_reimplemented(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("SupplierComparisonEngine", source)
        self.assertIn("negotiation_target_from_competing_quote", source)
        declared = {
            node.name
            for node in ast.walk(self.tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        for reimplementation in (
            "SupplierQuote",
            "SupplierQuoteLine",
            "Money",
            "PaymentTerms",
            "NegotiationDraft",
            "ComparisonMode",
            "ComparisonWeights",
            "SupplierComparisonAnalysis",
            "SupplierComparisonEngine",
        ):
            self.assertNotIn(reimplementation, declared)
        self.assertEqual(
            {node.name for node in ast.walk(self.tree) if isinstance(node, ast.ClassDef)},
            {"OpsQuoteCompareFlowError", "SupplierQuoteComparisonOutcome"},
        )


if __name__ == "__main__":
    unittest.main()
