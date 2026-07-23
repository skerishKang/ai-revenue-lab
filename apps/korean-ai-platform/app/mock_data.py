"""Deterministic demo catalog and seed data.

Everything here is synthetic. Model names are illustrative and are shown with
a Demo badge in the UI; none of them is actually connected.
"""

from __future__ import annotations

from app.domain import (
    BranchMode,
    ChangedFile,
    ExternalPolicy,
    ModelSpec,
    Project,
    Task,
    TestResult,
    TestSummary,
)


MODELS: list[ModelSpec] = [
    ModelSpec(
        id="openai-gpt",
        provider="OpenAI",
        name="GPT-4o (Demo)",
        region_label="해외 전송 (미국)",
        hosting_label="외부 클라우드",
        cost_class="paid",
        input_krw_per_1k=6.0,
        output_krw_per_1k=24.0,
    ),
    ModelSpec(
        id="anthropic-claude",
        provider="Anthropic",
        name="Claude Sonnet (Demo)",
        region_label="해외 전송 (미국)",
        hosting_label="외부 클라우드",
        cost_class="paid",
        input_krw_per_1k=4.0,
        output_krw_per_1k=20.0,
    ),
    ModelSpec(
        id="google-gemini",
        provider="Google",
        name="Gemini Pro (Demo)",
        region_label="해외 전송 (미국)",
        hosting_label="외부 클라우드",
        cost_class="paid",
        input_krw_per_1k=1.5,
        output_krw_per_1k=6.0,
    ),
    ModelSpec(
        id="domestic-open",
        provider="자체 호스팅",
        name="Ko-Open 32B (자체 GPU)",
        region_label="국내 처리 (자체 GPU)",
        hosting_label="자체 호스팅",
        cost_class="local",
        input_krw_per_1k=0.0,
        output_krw_per_1k=0.0,
        is_domestic=True,
    ),
    ModelSpec(
        id="byok-model",
        provider="사용자 API 키",
        name="BYOK 엔드포인트 (Demo)",
        region_label="설정된 엔드포인트로 전송",
        hosting_label="사용자 지정",
        cost_class="paid",
        input_krw_per_1k=3.0,
        output_krw_per_1k=12.0,
        requires_byok=True,
    ),
]


PROJECTS: list[Project] = [
    Project(
        id="commerce-backend",
        name="상거래 백엔드",
        repo_label="github.com/example/commerce-backend (Demo)",
        description="주문·결제·재고를 다루는 Python 백엔드 저장소입니다.",
        default_allowed=["app/", "tests/"],
        default_denied=["migrations/"],
    ),
    Project(
        id="data-pipeline",
        name="데이터 파이프라인",
        repo_label="github.com/example/data-pipeline (Demo)",
        description="야간 배치와 적재 작업을 관리하는 데이터 처리 저장소입니다.",
        default_allowed=["src/", "tests/"],
        default_denied=["infra/", "secrets/"],
    ),
    Project(
        id="internal-docs",
        name="사내 문서 도구",
        repo_label="github.com/example/internal-docs (Demo)",
        description="사내 문서 검색과 편집을 제공하는 웹 도구입니다.",
        default_allowed=["docs/", "web/"],
        default_denied=[],
    ),
]


PLAN_TEXT = """1. `app/services/order_service.py`의 주문 생성 함수에 재고 검증 단계를 추가합니다.
2. `app/api/routes/orders.py`에서 잘못된 요청에 대한 응답 코드를 정리합니다.
3. `tests/test_order_service.py`에 재고 부족·정상 주문 경계 테스트를 추가합니다.
4. 로컬 테스트를 실행해 회귀가 없는지 확인합니다."""


WORKER_CLAIM = (
    "요청하신 재고 검증 로직을 구현했고 테스트도 모두 통과했습니다. "
    "세 파일을 수정했으며 추가 검토는 필요하지 않습니다."
)


def _diff_order_service() -> str:
    return """@@ -18,6 +18,15 @@ def create_order(cart, warehouse):
     if not cart.items:
         raise EmptyCartError()
+    for line in cart.items:
+        available = warehouse.stock(line.sku)
+        if available < line.quantity:
+            raise InsufficientStockError(line.sku, available)
     order = Order(cart=cart)
     return order"""


def _diff_orders_route() -> str:
    return """@@ -40,7 +40,11 @@ async def create_order_endpoint(payload: OrderIn):
-    order = service.create_order(payload.cart, warehouse)
-    return {"id": order.id}
+    try:
+        order = service.create_order(payload.cart, warehouse)
+    except InsufficientStockError as exc:
+        raise HTTPException(status_code=409, detail=str(exc))
+    return {"id": order.id, "status": order.status}"""


def _diff_tests() -> str:
    return """@@ -0,0 +1,18 @@
+def test_create_order_rejects_when_stock_short():
+    warehouse = FakeWarehouse({"sku-1": 1})
+    cart = Cart([Line("sku-1", 3)])
+    with pytest.raises(InsufficientStockError):
+        create_order(cart, warehouse)
+
+def test_create_order_succeeds_at_exact_stock():
+    warehouse = FakeWarehouse({"sku-1": 3})
+    cart = Cart([Line("sku-1", 3)])
+    order = create_order(cart, warehouse)
+    assert order.status == "created\""""


CHANGED_FILES: list[ChangedFile] = [
    ChangedFile(
        path="app/services/order_service.py",
        additions=9,
        deletions=0,
        language="python",
        diff=_diff_order_service(),
    ),
    ChangedFile(
        path="app/api/routes/orders.py",
        additions=5,
        deletions=2,
        language="python",
        diff=_diff_orders_route(),
    ),
    ChangedFile(
        path="tests/test_order_service.py",
        additions=18,
        deletions=0,
        language="python",
        diff=_diff_tests(),
    ),
]


def base_tests() -> TestSummary:
    return TestSummary(
        command="pytest -q",
        total=24,
        passed=23,
        failed=0,
        skipped=1,
        results=[
            TestResult(name="test_create_order_rejects_when_stock_short", status="passed"),
            TestResult(name="test_create_order_succeeds_at_exact_stock", status="passed"),
            TestResult(name="test_order_totals_with_discount", status="passed"),
            TestResult(name="test_payment_capture_flow", status="passed"),
            TestResult(
                name="test_legacy_export_compat",
                status="skipped",
                detail="레거시 내보내기 호환 테스트는 이번 범위에서 건너뜀",
            ),
        ],
    )


def models_by_id() -> dict[str, ModelSpec]:
    return {m.id: m for m in MODELS}


def projects_by_id() -> dict[str, Project]:
    return {p.id: p for p in PROJECTS}


def build_seed_tasks() -> list[Task]:
    """Create a few demo tasks in different states for the dashboard."""
    from app import engine

    models = models_by_id()

    ready = Task(
        id="t-demo-004",
        title="결제 취소 API 오류 메시지 개선",
        instruction="결제 취소 실패 시 사용자에게 원인을 명확히 안내하도록 오류 메시지를 개선해 주세요.",
        project_id="commerce-backend",
        worker_model_id="domestic-open",
        validator_model_id="anthropic-claude",
        allowed_paths=["app/", "tests/"],
        denied_paths=["migrations/"],
        cost_limit_krw=3000.0,
        external_policy=ExternalPolicy.RESTRICT,
        branch_mode=BranchMode.AUTO,
    )

    awaiting = Task(
        id="t-demo-003",
        title="주문 목록 페이지 성능 개선",
        instruction="주문 목록 조회 시 N+1 쿼리를 제거하고 페이지네이션을 추가해 주세요.",
        project_id="commerce-backend",
        worker_model_id="openai-gpt",
        validator_model_id="anthropic-claude",
        allowed_paths=["app/", "tests/"],
        denied_paths=["migrations/"],
        cost_limit_krw=5000.0,
        external_policy=ExternalPolicy.ALLOW,
        branch_mode=BranchMode.AUTO,
    )
    engine.run_task(awaiting, models)

    rework = Task(
        id="t-demo-002",
        title="재고 동기화 배치 안정화",
        instruction="야간 재고 동기화 배치의 재시도 로직을 보완해 주세요.",
        project_id="data-pipeline",
        worker_model_id="google-gemini",
        validator_model_id="domestic-open",
        allowed_paths=["src/", "tests/"],
        denied_paths=["infra/", "secrets/"],
        cost_limit_krw=2000.0,
        external_policy=ExternalPolicy.ALLOW,
        branch_mode=BranchMode.MANUAL,
    )
    engine.run_task(rework, models)
    engine.request_rework(rework, "재시도 간격 정책이 지시와 다릅니다. 백오프를 적용해 주세요.", models)

    completed = Task(
        id="t-demo-001",
        title="주문 생성 시 재고 검증 추가",
        instruction="주문 생성 시 재고가 부족하면 실패하도록 검증 로직을 추가하고 테스트를 작성해 주세요.",
        project_id="commerce-backend",
        worker_model_id="openai-gpt",
        validator_model_id="anthropic-claude",
        allowed_paths=["app/", "tests/"],
        denied_paths=["migrations/"],
        cost_limit_krw=5000.0,
        external_policy=ExternalPolicy.ALLOW,
        branch_mode=BranchMode.AUTO,
    )
    engine.run_task(completed, models)
    engine.approve_task(completed, approver="검토자 김")

    return [completed, awaiting, rework, ready]
