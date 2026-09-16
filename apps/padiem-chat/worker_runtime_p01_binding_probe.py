from __future__ import annotations

import json
from urllib.parse import urlparse

from workers import Request, Response, WorkerEntrypoint

from app.claw_p01_composition import build_claw_p01_adapter
from app.worker_config import P01_ENGINE_SERVICE_BINDING_NAME
from kagent.contracts import ClawTaskIntent, ExecutionMode
from kagent.p01_adapter import P01AdapterError, P01CoreOrchestrationAdapter, P01_FAILURE_DETAILS
from kagent.runs import ClawRun
from padiem_control_plane.product_tier_routes import ProductTierLabel


_CALLER_ID = "b54-p01-overlay-20260914-a1"
_SYNTHETIC_CREDENTIAL = "c" * 48


class _SyntheticPostFetchBinding:
    """Stops after the real Worker Request/js_object boundary; no network is used."""

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, request):
        del request
        self.calls += 1
        return Response(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "synthetic_post_fetch_stop",
                        "message": "synthetic post-fetch stop",
                    },
                }
            ),
            status=503,
            headers={"Content-Type": "application/json"},
        )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(str(request.url)).path
        if path == "/ready":
            return Response("ok", status=200)
        if path != "/probe":
            return Response("not found", status=404)

        result = {
            "adapter_composed": False,
            "worker_request_factory_real": False,
            "plus_route_entered": False,
            "binding_fetch_called_once": False,
            "bounded_error_after_fetch": False,
            "unexpected_exception": False,
        }

        binding = _SyntheticPostFetchBinding()
        env = {
            P01_ENGINE_SERVICE_BINDING_NAME: binding,
            "P01_ENGINE_CALLER_ID": _CALLER_ID,
            "P01_ENGINE_CREDENTIAL": _SYNTHETIC_CREDENTIAL,
        }

        try:
            adapter = build_claw_p01_adapter(env, request_factory=Request)
            result["adapter_composed"] = isinstance(adapter, P01CoreOrchestrationAdapter)
            result["worker_request_factory_real"] = Request.__module__.startswith("workers")
            if adapter is None:
                raise RuntimeError("adapter composition failed")

            run = ClawRun.create(
                "run_worker_p01_probe",
                ClawTaskIntent(
                    task_id="task_worker_p01_probe",
                    task="synthetic P01 composition probe",
                    repository_ref="skerishKang/example",
                    execution_mode=ExecutionMode.LOCAL,
                ),
            )
            result["plus_route_entered"] = True
            try:
                await adapter.execute(run, product_tier=ProductTierLabel.PLUS)
            except P01AdapterError as exc:
                result["binding_fetch_called_once"] = binding.calls == 1
                result["bounded_error_after_fetch"] = (
                    binding.calls == 1
                    and exc.failure_detail in P01_FAILURE_DETAILS
                )
            else:
                result["binding_fetch_called_once"] = binding.calls == 1
        except Exception as exc:
            result["unexpected_exception"] = True
            result["error_type"] = type(exc).__name__

        ok = (
            result["adapter_composed"]
            and result["worker_request_factory_real"]
            and result["plus_route_entered"]
            and result["binding_fetch_called_once"]
            and result["bounded_error_after_fetch"]
            and not result["unexpected_exception"]
        )
        return Response(
            json.dumps(result, sort_keys=True),
            status=200 if ok else 500,
            headers={"Content-Type": "application/json"},
        )
