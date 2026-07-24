"""Routes for the Korean AI API Provider Phase 0 Mock Demo."""

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
    generate_demo_key,
    generate_demo_response,
    get_integration_examples,
    mark_key_revoked,
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
            "routing_policies": ROUTING_POLICIES,
        },
    )


@router.get("/models")
def model_catalog(request: Request):
    filter_type = request.query_params.get("type", "")
    search = request.query_params.get("q", "").strip().lower()
    sort = request.query_params.get("sort", "recommended")

    models = list(MODELS)

    if filter_type in ("external", "domestic", "open-model"):
        models = [m for m in models if m.provider_type == filter_type]
    elif filter_type == "korean":
        models = [m for m in models if m.korean_score >= 5]
    elif filter_type == "coding":
        models = [m for m in models if m.coding_score >= 4]
    elif filter_type == "long-context":
        models = [m for m in models if m.long_context]
    elif filter_type == "image":
        models = [m for m in models if m.image_input]
    elif filter_type == "low-cost":
        models = [m for m in models if m.low_cost]

    if search:
        models = [
            m for m in models
            if search in m.name.lower()
            or search in m.provider.lower()
            or any(search in t.lower() for t in m.tags)
        ]

    if sort == "price-asc":
        models.sort(key=lambda m: m.input_krw_per_1k + m.output_krw_per_1k)
    elif sort == "speed":
        models.sort(key=lambda m: m.latency_ms)
    elif sort == "context":
        models.sort(key=lambda m: -m.context_window)
    elif sort == "korean":
        models.sort(key=lambda m: -m.korean_score)

    return render_template(
        request,
        "models.html",
        {
            "models": models,
            "all_models": MODELS,
            "filter_type": filter_type,
            "search": search,
            "sort": sort,
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
    model_id = request.query_params.get("model", "")
    if model_id and model_id not in MODELS_BY_ID:
        model_id = ""
    if not model_id:
        model_id = MODELS[0].id
    return render_template(
        request,
        "playground.html",
        {
            "models": MODELS,
            "routing_policies": ROUTING_POLICIES,
            "result": None,
            "error": None,
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
    if routing_mode != "direct" and routing_mode:
        for policy in ROUTING_POLICIES:
            if policy.id == routing_mode:
                model_id = policy.selected_model_id
                break

    if not model_id or model_id not in MODELS_BY_ID:
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
            "error": None,
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
    model_id = request.query_params.get("model", "")
    if not model_id or model_id not in MODELS_BY_ID:
        model_id = MODELS[0].id
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


@router.get("/pricing")
def pricing(request: Request):
    return render_template(request, "pricing.html", {})


@router.get("/access")
def access(request: Request):
    return render_template(
        request,
        "access.html",
        {"access_modes": ACCESS_MODES},
    )
