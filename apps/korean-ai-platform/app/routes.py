"""Web routes for the Korean AI Platform demo MVP.

All state changes go through the deterministic engine. A task only receives a
mock commit SHA and branch name after an explicit human approval.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import engine
from app.domain import TaskStatus
from app.factory import render_template
from app.store import ByokState, Store, create_task, parse_cost_limit

router = APIRouter()


def _store(request: Request) -> Store:
    return request.app.state.store


def _error_redirect(task_id: str, message: object) -> RedirectResponse:
    """Build a redirect carrying an error message safely.

    The message (a fixed Korean engine string) is percent-encoded so the
    Location header stays pure ASCII; raw non-ASCII bytes in a header would
    make a real ASGI server fail the response.
    """
    return RedirectResponse(
        url=f"/tasks/{quote(task_id)}?error={quote(str(message))}",
        status_code=303,
    )


@router.get("/")
def dashboard(request: Request):
    store = _store(request)
    counts = store.status_counts()
    active = sum(
        counts.get(s.value, 0)
        for s in (
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.AWAITING_APPROVAL,
            TaskStatus.REWORK,
        )
    )
    settings = store.settings
    tasks = store.list_tasks()
    policy_alerts = sum(
        1
        for t in tasks
        if t.run is not None and (t.run.path_violations or t.run.over_budget)
    )
    context = {
        "tasks": tasks,
        "counts": counts,
        "active_count": active,
        "project_count": len(store.projects),
        "monthly_krw": store.monthly_estimated_krw(),
        "settings": settings,
        "models_map": store.models,
        "projects_map": store.projects,
        "policy_alerts": policy_alerts,
    }
    return render_template(request, "dashboard.html", context)


@router.get("/tasks/new")
def task_new(request: Request):
    store = _store(request)
    return render_template(
        request,
        "task_new.html",
        {
            "projects": list(store.projects.values()),
            "models": list(store.models.values()),
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
    store = _store(request)
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
    task, errors = create_task(store, form)
    if task is None:
        return render_template(
            request,
            "task_new.html",
            {
                "projects": list(store.projects.values()),
                "models": list(store.models.values()),
                "errors": errors,
                "form": form,
            },
        )
    return RedirectResponse(url=f"/tasks/{task.id}", status_code=303)


@router.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: str):
    store = _store(request)
    task = store.get_task(task_id)
    if task is None:
        return render_template(
            request, "not_found.html", {"task_id": task_id}, status_code=404
        )
    context = {
        "task": task,
        "project": store.projects.get(task.project_id),
        "worker_model": store.models.get(task.worker_model_id),
        "validator_model": store.models.get(task.validator_model_id),
        "regions": engine.data_regions(task, store.models),
        "settings": store.settings,
        "error": request.query_params.get("error"),
    }
    return render_template(request, "task_detail.html", context)


@router.post("/tasks/{task_id}/run")
def task_run(request: Request, task_id: str):
    store = _store(request)
    task = store.get_task(task_id)
    if task is None:
        return RedirectResponse(url="/", status_code=303)
    try:
        engine.run_task(task, store.models)
    except engine.IllegalTransition as exc:
        return _error_redirect(task_id, exc)
    return RedirectResponse(url=f"/tasks/{task_id}?ran=1", status_code=303)


@router.post("/tasks/{task_id}/approve")
def task_approve(request: Request, task_id: str, approver: str = Form("")):
    store = _store(request)
    task = store.get_task(task_id)
    if task is None:
        return RedirectResponse(url="/", status_code=303)
    try:
        engine.approve_task(task, approver)
    except engine.IllegalTransition as exc:
        return _error_redirect(task_id, exc)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/rework")
def task_rework(request: Request, task_id: str, reason: str = Form("")):
    store = _store(request)
    task = store.get_task(task_id)
    if task is None:
        return RedirectResponse(url="/", status_code=303)
    try:
        engine.request_rework(task, reason, store.models)
    except (engine.IllegalTransition, ValueError) as exc:
        return _error_redirect(task_id, exc)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/reject")
def task_reject(request: Request, task_id: str, reason: str = Form("")):
    store = _store(request)
    task = store.get_task(task_id)
    if task is None:
        return RedirectResponse(url="/", status_code=303)
    try:
        engine.reject_task(task, reason)
    except engine.IllegalTransition as exc:
        return _error_redirect(task_id, exc)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.get("/settings")
def settings_page(request: Request):
    store = _store(request)
    byok_models = [m for m in store.models.values() if m.requires_byok]
    return render_template(
        request,
        "settings.html",
        {
            "settings": store.settings,
            "models": list(store.models.values()),
            "byok_models": byok_models,
            "saved": request.query_params.get("saved"),
        },
    )


@router.post("/settings")
async def settings_save(request: Request):
    store = _store(request)
    form = await request.form()
    settings = store.settings

    settings.domestic_first = form.get("domestic_first") == "on"
    settings.allow_external = form.get("allow_external") == "on"
    settings.block_on_secret = form.get("block_on_secret") == "on"
    settings.block_push_without_approval = form.get("block_push_without_approval") == "on"

    parsed_limit, limit_error = parse_cost_limit(
        str(form.get("project_cost_limit_krw") or "")
    )
    if limit_error is None and parsed_limit is not None:
        settings.project_cost_limit_krw = parsed_limit

    for model in store.models.values():
        if not model.requires_byok:
            continue
        state = settings.byok.setdefault(model.id, ByokState())
        # The API key value is read only to detect presence and is then
        # discarded. Only the boolean registration flag is kept (Demo).
        state.registered = bool(str(form.get(f"apikey_{model.id}", "")).strip())

    return RedirectResponse(url="/settings?saved=1", status_code=303)
