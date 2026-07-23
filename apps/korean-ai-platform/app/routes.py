"""Web routes for the Korean AI Platform demo MVP.

Routes are thin: they delegate to the application service, which owns the
transition-unit transactions. A task only receives a mock commit SHA and branch
name after an explicit human approval (AUTO branch mode). DB failures surface a
fixed safe message and never produce a success redirect.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import engine
from app.db import PersistenceError
from app.domain import TaskStatus
from app.factory import render_template
from app.services import BaseTaskService, TaskNotFound

router = APIRouter()


def _service(request: Request) -> BaseTaskService:
    return request.app.state.service


def _error_redirect(task_id: str, message: object) -> RedirectResponse:
    """Redirect carrying a percent-encoded error (ASCII-safe Location header)."""
    return RedirectResponse(
        url=f"/tasks/{quote(task_id)}?error={quote(str(message))}",
        status_code=303,
    )


@router.get("/")
def dashboard(request: Request):
    service = _service(request)
    counts = service.status_counts()
    active = sum(
        counts.get(s.value, 0)
        for s in (
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.AWAITING_APPROVAL,
            TaskStatus.REWORK,
        )
    )
    settings = service.get_settings()
    tasks = service.list_tasks()
    policy_alerts = sum(
        1
        for t in tasks
        if t.run is not None and (t.run.path_violations or t.run.over_budget)
    )
    context = {
        "tasks": tasks,
        "counts": counts,
        "active_count": active,
        "project_count": len(service.projects),
        "monthly_krw": service.monthly_estimated_krw(),
        "settings": settings,
        "models_map": service.models,
        "projects_map": service.projects,
        "policy_alerts": policy_alerts,
    }
    return render_template(request, "dashboard.html", context)


@router.get("/tasks/new")
def task_new(request: Request):
    service = _service(request)
    return render_template(
        request,
        "task_new.html",
        {
            "projects": list(service.projects.values()),
            "models": list(service.models.values()),
            "errors": {},
            "form": {},
        },
    )


@router.post("/tasks")
def task_create(
    request: Request,
    title: str = Form(""),
    instruction: str = Form(""),
    project_id: str = Form(""),
    worker_model_id: str = Form(""),
    validator_model_id: str = Form(""),
    allowed_paths: str = Form(""),
    denied_paths: str = Form(""),
    cost_limit_krw: str = Form(""),
    external_policy: str = Form("allow"),
    branch_mode: str = Form("auto"),
):
    service = _service(request)
    form = {
        "title": title,
        "instruction": instruction,
        "project_id": project_id,
        "worker_model_id": worker_model_id,
        "validator_model_id": validator_model_id,
        "allowed_paths": allowed_paths,
        "denied_paths": denied_paths,
        "cost_limit_krw": cost_limit_krw,
        "external_policy": external_policy,
        "branch_mode": branch_mode,
    }
    try:
        task, errors = service.create_task(form)
    except PersistenceError as exc:
        errors = {"_form": str(exc)}
        task = None
    if task is None:
        return render_template(
            request,
            "task_new.html",
            {
                "projects": list(service.projects.values()),
                "models": list(service.models.values()),
                "errors": errors,
                "form": form,
            },
        )
    return RedirectResponse(url=f"/tasks/{task.id}", status_code=303)


@router.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: str):
    service = _service(request)
    task = service.get_task(task_id)
    if task is None:
        return render_template(
            request, "not_found.html", {"task_id": task_id}, status_code=404
        )
    context = {
        "task": task,
        "project": service.projects.get(task.project_id),
        "worker_model": service.models.get(task.worker_model_id),
        "validator_model": service.models.get(task.validator_model_id),
        "regions": service.data_regions(task),
        "settings": service.get_settings(),
        "error": request.query_params.get("error"),
    }
    return render_template(request, "task_detail.html", context)


@router.post("/tasks/{task_id}/run")
def task_run(request: Request, task_id: str):
    service = _service(request)
    try:
        service.run_task(task_id)
    except TaskNotFound:
        return RedirectResponse(url="/", status_code=303)
    except PersistenceError as exc:
        return _error_redirect(task_id, exc)
    except (engine.IllegalTransition, ValueError) as exc:
        return _error_redirect(task_id, exc)
    return RedirectResponse(url=f"/tasks/{task_id}?ran=1", status_code=303)


@router.post("/tasks/{task_id}/approve")
def task_approve(request: Request, task_id: str, approver: str = Form("")):
    service = _service(request)
    try:
        service.approve_task(task_id, approver)
    except TaskNotFound:
        return RedirectResponse(url="/", status_code=303)
    except PersistenceError as exc:
        return _error_redirect(task_id, exc)
    except (engine.IllegalTransition, ValueError) as exc:
        return _error_redirect(task_id, exc)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/rework")
def task_rework(request: Request, task_id: str, reason: str = Form("")):
    service = _service(request)
    try:
        service.request_rework(task_id, reason)
    except TaskNotFound:
        return RedirectResponse(url="/", status_code=303)
    except PersistenceError as exc:
        return _error_redirect(task_id, exc)
    except (engine.IllegalTransition, ValueError) as exc:
        return _error_redirect(task_id, exc)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/reject")
def task_reject(request: Request, task_id: str, reason: str = Form("")):
    service = _service(request)
    try:
        service.reject_task(task_id, reason)
    except TaskNotFound:
        return RedirectResponse(url="/", status_code=303)
    except PersistenceError as exc:
        return _error_redirect(task_id, exc)
    except (engine.IllegalTransition, ValueError) as exc:
        return _error_redirect(task_id, exc)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.get("/settings")
def settings_page(request: Request):
    service = _service(request)
    settings = service.get_settings()
    byok_models = [m for m in service.models.values() if m.requires_byok]
    return render_template(
        request,
        "settings.html",
        {
            "settings": settings,
            "models": list(service.models.values()),
            "byok_models": byok_models,
            "saved": request.query_params.get("saved"),
            "errors": {},
            "form": None,
        },
    )


@router.post("/settings")
async def settings_save(request: Request):
    service = _service(request)
    raw_form = await request.form()
    form = {key: str(raw_form.get(key)) for key in raw_form.keys()}
    # Preserve checkbox semantics: absent checkbox -> "" (treated as off).
    try:
        ok, errors = service.save_settings(form)
    except PersistenceError as exc:
        byok_models = [m for m in service.models.values() if m.requires_byok]
        return render_template(
            request,
            "settings.html",
            {
                "settings": service.get_settings(),
                "models": list(service.models.values()),
                "byok_models": byok_models,
                "saved": None,
                "errors": {"_form": str(exc)},
                "form": form,
            },
        )
    if not ok:
        byok_models = [m for m in service.models.values() if m.requires_byok]
        return render_template(
            request,
            "settings.html",
            {
                "settings": service.get_settings(),
                "models": list(service.models.values()),
                "byok_models": byok_models,
                "saved": None,
                "errors": errors,
                "form": form,
            },
        )
    return RedirectResponse(url="/settings?saved=1", status_code=303)
