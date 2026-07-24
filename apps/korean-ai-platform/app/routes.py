"""Routes for the Korean AI API Provider Phase 0 Demo."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.demo_data import (
    ACCESS_MODES,
    DEMO_API_KEYS,
    DEMO_USAGE_RECORDS,
    MODELS,
    MODELS_BY_ID,
    ROUTING_POLICIES,
    REVOKED_KEY_IDS,
    compute_usage_summary,
    generate_demo_key,
    generate_demo_response,
    get_available_models,
    get_integration_examples,
    mark_key_revoked,
)
from app.factory import render_template

router = APIRouter()


@router.get("/")
def home(request: Request):
    available = get_available_models()
    return render_template(
        request,
        "home.html",
        {
            "models": available,
            "model_count": len(available),
            "provider_types": ["external", "domestic", "self-hosted"],
        },
    )


@router.get("/models")
def model_catalog(request: Request):
    filter_type = request.query_params.get("type", "")
    available = get_available_models()
    models = available
    if filter_type in ("external", "domestic", "self-hosted"):
        models = [m for m in available if m.provider_type == filter_type]
    return render_template(
        request,
        "models.html",
        {
            "models": models,
            "all_models": available,
            "filter_type": filter_type,
        },
    )


@router.get("/models/{model_id}")
def model_detail(request: Request, model_id: str):
    model = MODELS_BY_ID.get(model_id)
    if model is None:
        return render_template(request, "not_found.html", {"item": "모델"}, status_code=404)
    examples = get_integration_examples(model_id)
    return render_template(
        request,
        "model_detail.html",
        {"model": model, "examples": examples},
    )


@router.get("/playground")
def playground(request: Request):
    available = get_available_models()
    model_id = request.query_params.get("model", "")
    if model_id and model_id not in {m.id for m in available}:
        model_id = ""
    if not model_id and available:
        model_id = available[0].id
    return render_template(
        request,
        "playground.html",
        {
            "models": available,
            "routing_policies": ROUTING_POLICIES,
            "result": None,
            "prompt": "",
            "selected_model": model_id,
            "routing_mode": "direct",
        },
    )


@router.post("/playground")
def playground_run(
    request: Request,
    prompt: str = Form(""),
    model_id: str = Form(""),
    routing_mode: str = Form("direct"),
):
    available = get_available_models()
    available_ids = {m.id for m in available}

    if routing_mode != "direct" and routing_mode:
        for policy in ROUTING_POLICIES:
            if policy.id == routing_mode:
                model_id = policy.selected_model_id
                break

    result = None
    error = None
    if prompt.strip():
        if model_id and model_id in available_ids:
            result = generate_demo_response(model_id, prompt, routing_mode)
        else:
            model_id = ""
            error = "선택한 모델은 Demo를 지원하지 않습니다."

    if not model_id and available:
        model_id = available[0].id

    return render_template(
        request,
        "playground.html",
        {
            "models": available,
            "routing_policies": ROUTING_POLICIES,
            "result": result,
            "error": error,
            "prompt": prompt,
            "selected_model": model_id,
            "routing_mode": routing_mode,
        },
    )


@router.get("/api-keys")
def api_keys(request: Request):
    created = request.query_params.get("created")
    revoked = request.query_params.get("revoked")
    invalid = request.query_params.get("invalid")
    keys = list(DEMO_API_KEYS)
    if created:
        new_key = generate_demo_key()
        keys = [new_key] + keys
    return render_template(
        request,
        "api_keys.html",
        {
            "keys": keys,
            "access_modes": ACCESS_MODES,
            "created": created,
            "revoked": revoked,
            "invalid": invalid,
        },
    )


@router.post("/api-keys/create")
def api_key_create(request: Request):
    return RedirectResponse(url="/api-keys?created=1", status_code=303)


@router.post("/api-keys/{key_id}/revoke")
def api_key_revoke(request: Request, key_id: str):
    valid_ids = {k.id for k in DEMO_API_KEYS}
    if key_id not in valid_ids:
        return RedirectResponse(url="/api-keys?invalid=1", status_code=303)
    mark_key_revoked(key_id)
    return RedirectResponse(url=f"/api-keys?revoked={key_id}", status_code=303)


@router.get("/usage")
def usage(request: Request):
    summary = compute_usage_summary()
    return render_template(
        request,
        "usage.html",
        {
            "summary": summary,
            "records": DEMO_USAGE_RECORDS,
        },
    )


@router.get("/docs")
def docs(request: Request):
    available = get_available_models()
    model_id = request.query_params.get("model", "")
    if not model_id or model_id not in {m.id for m in available}:
        model_id = available[0].id if available else "openai-gpt4o"
    examples = get_integration_examples(model_id)
    return render_template(
        request,
        "docs.html",
        {
            "examples": examples,
            "models": available,
            "selected_model": model_id,
        },
    )


@router.get("/access")
def access(request: Request):
    return render_template(
        request,
        "access.html",
        {"access_modes": ACCESS_MODES},
    )
