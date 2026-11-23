"""#7543 전수표 회귀 가드 — 새 프로세스 전역 상태·반복 작업이 생기면 실패한다.

11-17 전수표와 그 뒤 재조사에서 확인한 시동 훅·백그라운드 태스크·변경되는
모듈 전역을 여기에 고정한다. 새 항목이 추가되면 이 시험이 먼저 실패하므로
#7543 표에 판정을 적은 뒤 기대값을 갱신한다. 코드는 읽기만 하고 운영 설정이나
비밀값은 쓰지 않는다.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# (파일, 훅, 등록 함수) -> 등록 횟수. 11-17 표의 S04/S36과 재조사 3건 포함.
HOOKS = {
    ("app_factory.py", "on_shutdown", "drain_background_runs"): 1,
    ("local_cpython.py", "on_shutdown", "_stop_bound_wal"): 1,
    ("local_cpython.py", "on_shutdown", "closure"): 4,
    ("local_cpython.py", "on_shutdown", "exchange_close"): 1,
    ("local_cpython.py", "on_shutdown", "stop_identity_cache_metrics"): 1,
    ("local_cpython.py", "on_startup", "_arm_identity_keepwarm_on_startup"): 1,
    ("local_cpython.py", "on_startup", "_bound_wal_on_startup"): 1,
    ("local_cpython.py", "on_startup", "_compose_oracle_mesh_return_source_on_startup"): 1,
    ("loop_stall_watchdog.py", "on_shutdown", "_stop"): 1,
    ("loop_stall_watchdog.py", "on_startup", "_start"): 1,
    ("lovetree_ops_outbox.py", "on_shutdown", "closure"): 1,
    ("lovetree_ops_outbox.py", "on_startup", "start"): 1,
    ("ops_alert_delivery.py", "on_shutdown", "closure"): 1,
    ("ops_alert_delivery.py", "on_startup", "start"): 1,
    ("pc_helper_maintenance_host.py", "on_shutdown", "closure"): 1,
    ("pc_helper_maintenance_host.py", "on_startup", "start"): 1,
}

# 파일별 asyncio.create_task 횟수. 요청 수명 태스크와 시동 루프를 함께 센다.
TASK_COUNTS = {
    "auth_validation_cache.py": 2,
    "claw_live_events.py": 1,
    "claw_routes.py": 1,
    "com2_pc_offer_relay.py": 2,
    "connector_account_shadow.py": 4,
    "document_convert_routes.py": 1,
    "identity_call_cache.py": 1,
    "local_cpython.py": 1,
    "loop_stall_watchdog.py": 1,
    "lovetree_ops_outbox.py": 2,
    "ops_alert_delivery.py": 2,
    "pc_helper_maintenance_host.py": 1,
    "worker_cache_generation.py": 1,
}

# 실제로 값이 바뀌는 모듈 전역. 상수 표현식(__all__·_NO_STORE 등)은 제외.
STATEFUL_GLOBALS = {
    ("auth_shadow_verify.py", "_denylist"),
    ("auth_shadow_verify.py", "_refresh_state"),
    ("b66_ai_chat_routes.py", "_RECENT_TURNS"),
    ("chat_connector_tools.py", "_GRANT_CACHE"),
    ("claw_routes.py", "_CLAW_EXECUTE_IDEMPOTENCY_CACHE"),
    ("control_plane_identity_worker.py", "_generation_store"),
    ("control_plane_identity_worker.py", "_product_user_cache"),
    ("document_convert_routes.py", "_BACKGROUND_RUNS"),
    ("identity_cache_metrics.py", "_counts"),
    ("identity_cache_metrics.py", "_rpc_counts"),
    ("ops_pc_self_heal.py", "_reports"),
    ("owner_model_preview_routes.py", "_ROSTER_CACHE"),
    ("owner_model_preview_routes.py", "_ROSTER_LOCKS"),
    ("owner_model_preview_routes.py", "_ROSTER_REFRESH"),
    ("pc_scope_cache.py", "_CACHE"),
    ("pc_scope_cache.py", "_LOCKS"),
    ("tus_core.py", "_PATCH_LOCKS"),
    ("worker_cache_generation.py", "_DEFAULT_STORE"),
    ("worker_cache_generation.py", "_LAST_KNOWN"),
}

_MUTABLE = (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)
_LOCK_FACTORIES = {"Lock", "RLock", "Event", "Condition", "deque", "defaultdict",
                   "OrderedDict", "ContextVar", "Semaphore"}
_MUTATORS = {"append", "add", "clear", "update", "pop", "popitem", "setdefault",
             "remove", "extend", "insert", "discard"}


def _read_facts():
    hooks, tasks = Counter(), Counter()
    stateful = set()
    for path in sorted(APP.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        candidates = set()
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if (isinstance(value, _MUTABLE)
                        or (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                            and value.func.id in _LOCK_FACTORIES)):
                    for target in targets:
                        if isinstance(target, ast.Name) and not target.id.startswith("__"):
                            candidates.add(target.id)
        mutated = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and isinstance(node.ctx, ast.Store) and node.value.id in candidates):
                mutated.add(node.value.id)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                func = node.func
                if (func.attr in _MUTATORS and isinstance(func.value, ast.Name)
                        and func.value.id in candidates):
                    mutated.add(func.value.id)
                if (func.attr in ("append", "insert") and isinstance(func.value, ast.Attribute)
                        and func.value.attr in ("on_startup", "on_shutdown")):
                    arg = node.args[0] if node.args else None
                    name = arg.id if isinstance(arg, ast.Name) else "closure"
                    hooks[(path.name, func.value.attr, name)] += 1
                if func.attr == "create_task":
                    tasks[path.name] += 1
            if isinstance(node, ast.Global):
                for name in node.names:
                    if name in candidates:
                        mutated.add(name)
        for name in mutated:
            stateful.add((path.name, name))
    return hooks, tasks, stateful


def test_lifespan_hooks_are_the_audited_set():
    hooks, _tasks, _globals = _read_facts()
    assert dict(hooks) == HOOKS, "새 시동 훅/반복 작업 — #7543 표에 판정을 추가할 것"


def test_background_task_sites_are_the_audited_set():
    _hooks, tasks, _globals = _read_facts()
    assert dict(tasks) == TASK_COUNTS, "새 asyncio.create_task — #7543 표에 판정을 추가할 것"


def test_stateful_module_globals_are_the_audited_set():
    _hooks, _tasks, stateful = _read_facts()
    assert stateful == STATEFUL_GLOBALS, "새 프로세스 전역 상태 — #7543 표에 판정을 추가할 것"
