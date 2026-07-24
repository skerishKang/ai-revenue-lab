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
    compute_usage_summary,
    generate_demo_response,
    get_integration_examples,
)
from app.factory import render_template

router = APIRouter()


@router.get("/")
def home(request: Request):
    return render_template(
        request,
        "home.html",
        {
            "models": MODELS,
            "model_count": len(MODELS),
            "provider_types": ["external", "domestic", "self-hosted"],
        },
    )


@router.get("/models")
def model_catalog(request: Request):
    filter_type = request.query_params.get("type", "")
    models = MODELS
    if filter_type in ("external", "domestic", "self-hosted"):
        models = [m for m in MODELS if m.provider_type == filter_type]
    return render_template(
        request,
        "models.html",
        {
            "models": models,
            "all_models": MODELS,
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
    return render_template(
        request,
        "playground.html",
        {
            "models": MODELS,
            "routing_policies": ROUTING_POLICIES,
            "result": None,
            "prompt": "",
            "selected_model": "",
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
    if routing_mode != "direct" and routing_mode:
        for policy in ROUTING_POLICIES:
            if policy.id == routing_mode:
                model_id = policy.selected_model_id
                break

    if not model_id:
        model_id = MODELS[0].id

    result = None
    if prompt.strip():
        result = generate_demo_response(model_id, prompt, routing_mode)

    return render_template(
        request,
        "playground.html",
        {
            "models": MODELS,
            "routing_policies": ROUTING_POLICIES,
            "result": result,
            "prompt": prompt,
            "selected_model": model_id,
            "routing_mode": routing_mode,
        },
    )


@router.get("/api-keys")
def api_keys(request: Request):
    return render_template(
        request,
        "api_keys.html",
        {
            "keys": DEMO_API_KEYS,
            "access_modes": ACCESS_MODES,
        },
    )


@router.post("/api-keys/create")
def api_key_create(request: Request):
    return RedirectResponse(url="/api-keys?created=1", status_code=303)


@router.post("/api-keys/{key_id}/revoke")
def api_key_revoke(request: Request, key_id: str):
    return RedirectResponse(url="/api-keys?revoked=1", status_code=303)


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
    model_id = request.query_params.get("model", "openai-gpt4o")
    examples = get_integration_examples(model_id)
    return render_template(
        request,
        "docs.html",
        {
            "examples": examples,
            "models": MODELS,
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
