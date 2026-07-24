"""Synthetic demo data for the Korean AI API Provider Phase 0 Demo.

All data is deterministic, network-free, and clearly labeled as Demo.
No real provider pricing, credentials, or customer data is included.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    provider_type: str
    name: str
    input_krw_per_1k: float
    output_krw_per_1k: float
    region: str
    korean_score: int
    coding_score: int
    long_context: bool
    image_input: bool
    low_cost: bool
    demo_available: bool
    tags: list[str] = field(default_factory=list)
    latency_ms: int = 800
    context_window: int = 8192


MODELS: list[ModelSpec] = [
    ModelSpec(
        id="openai-gpt4o",
        provider="OpenAI",
        provider_type="external",
        name="GPT-4o",
        input_krw_per_1k=3.5,
        output_krw_per_1k=14.0,
        region="미국",
        korean_score=4,
        coding_score=5,
        long_context=True,
        image_input=True,
        low_cost=False,
        demo_available=True,
        tags=["범용", "멀티모달", "긴 문맥"],
        latency_ms=900,
        context_window=128000,
    ),
    ModelSpec(
        id="anthropic-claude-sonnet",
        provider="Anthropic",
        provider_type="external",
        name="Claude Sonnet 4",
        input_krw_per_1k=4.0,
        output_krw_per_1k=20.0,
        region="미국",
        korean_score=4,
        coding_score=5,
        long_context=True,
        image_input=True,
        low_cost=False,
        demo_available=True,
        tags=["범용", "긴 문맥", "분석"],
        latency_ms=1100,
        context_window=200000,
    ),
    ModelSpec(
        id="google-gemini-pro",
        provider="Google",
        provider_type="external",
        name="Gemini 2.5 Pro",
        input_krw_per_1k=2.0,
        output_krw_per_1k=8.0,
        region="미국",
        korean_score=4,
        coding_score=4,
        long_context=True,
        image_input=True,
        low_cost=False,
        demo_available=True,
        tags=["범용", "멀티모달", "긴 문맥"],
        latency_ms=700,
        context_window=1000000,
    ),
    ModelSpec(
        id="naver-hyperclova-x",
        provider="Naver",
        provider_type="domestic",
        name="HyperCLOVA X",
        input_krw_per_1k=2.5,
        output_krw_per_1k=10.0,
        region="국내 (한국)",
        korean_score=5,
        coding_score=3,
        long_context=False,
        image_input=False,
        low_cost=False,
        demo_available=True,
        tags=["한국어 특화", "국내 처리"],
        latency_ms=600,
        context_window=32000,
    ),
    ModelSpec(
        id="kakao-kanana",
        provider="Kakao",
        provider_type="domestic",
        name="Kanana",
        input_krw_per_1k=1.8,
        output_krw_per_1k=7.0,
        region="국내 (한국)",
        korean_score=5,
        coding_score=3,
        long_context=False,
        image_input=False,
        low_cost=True,
        demo_available=True,
        tags=["한국어 특화", "국내 처리", "저비용"],
        latency_ms=500,
        context_window=16000,
    ),
    ModelSpec(
        id="ncsoft-varco",
        provider="NCSoft",
        provider_type="domestic",
        name="VARCO LLM",
        input_krw_per_1k=1.5,
        output_krw_per_1k=6.0,
        region="국내 (한국)",
        korean_score=5,
        coding_score=2,
        long_context=False,
        image_input=False,
        low_cost=True,
        demo_available=True,
        tags=["한국어 특화", "국내 처리", "저비용"],
        latency_ms=450,
        context_window=8192,
    ),
    ModelSpec(
        id="selfhost-ko-open",
        provider="오픈모델·전용 추론",
        provider_type="open-model",
        name="Ko-Open 32B",
        input_krw_per_1k=0.8,
        output_krw_per_1k=2.5,
        region="국내 (전용 추론)",
        korean_score=4,
        coding_score=3,
        long_context=False,
        image_input=False,
        low_cost=True,
        demo_available=True,
        tags=["오픈모델", "전용 추론", "국내 처리", "저비용"],
        latency_ms=350,
        context_window=32000,
    ),
    ModelSpec(
        id="selfhost-llama-ko",
        provider="오픈모델·전용 추론",
        provider_type="open-model",
        name="Llama-Ko 70B",
        input_krw_per_1k=1.0,
        output_krw_per_1k=3.0,
        region="국내 (전용 추론)",
        korean_score=3,
        coding_score=4,
        long_context=True,
        image_input=False,
        low_cost=True,
        demo_available=True,
        tags=["오픈모델", "전용 추론", "국내 처리", "저비용", "코딩"],
        latency_ms=500,
        context_window=128000,
    ),
]

MODELS_BY_ID: dict[str, ModelSpec] = {m.id: m for m in MODELS}


def get_available_models() -> list[ModelSpec]:
    return list(MODELS)


@dataclass(frozen=True)
class RoutingPolicy:
    id: str
    label: str
    description: str
    selected_model_id: str
    reason: str


ROUTING_POLICIES: list[RoutingPolicy] = [
    RoutingPolicy(
        id="cheapest",
        label="가장 저렴하게",
        description="Demo 가격 기준 가장 낮은 비용의 모델을 선택합니다.",
        selected_model_id="selfhost-ko-open",
        reason="Demo 가격 기준 최저 비용 모델 (Mock)",
    ),
    RoutingPolicy(
        id="fastest",
        label="가장 빠르게",
        description="Demo latency 기준 가장 빠른 모델을 선택합니다.",
        selected_model_id="selfhost-ko-open",
        reason="Demo latency 기준 최저 응답 시간 모델 (Mock)",
    ),
    RoutingPolicy(
        id="korean-first",
        label="한국어 우선",
        description="한국어 적합성이 가장 높은 모델을 선택합니다.",
        selected_model_id="naver-hyperclova-x",
        reason="한국어 적합성 최고 점수 모델 (Mock)",
    ),
    RoutingPolicy(
        id="domestic-first",
        label="국내·전용 추론 우선",
        description="국내 또는 전용 추론 모델을 우선 선택합니다.",
        selected_model_id="naver-hyperclova-x",
        reason="국내 처리 모델 중 최고 성능 (Mock)",
    ),
]


@dataclass(frozen=True)
class DemoResponse:
    model_id: str
    text: str
    input_tokens: int
    output_tokens: int
    cost_krw: float
    latency_ms: int
    region: str
    routing_reason: str


def generate_demo_response(
    model_id: str, prompt: str, routing_mode: str = "direct"
) -> DemoResponse:
    model = MODELS_BY_ID.get(model_id)
    if model is None:
        model = MODELS[0]

    routing_reason = "모델 직접 선택"
    if routing_mode != "direct":
        for policy in ROUTING_POLICIES:
            if policy.id == routing_mode:
                routing_reason = policy.reason
                break

    prompt_len = len(prompt)
    input_tokens = max(10, prompt_len // 2)
    output_tokens = 120 + (prompt_len % 50)
    cost_krw = (input_tokens / 1000 * model.input_krw_per_1k) + (
        output_tokens / 1000 * model.output_krw_per_1k
    )

    truncated_prompt = prompt[:80]
    if len(prompt) > 80:
        truncated_prompt += "…"

    sample_text = (
        f"[Demo 응답] {model.name} 모델이 생성한 예시 결과입니다. "
        f"실제 API 호출이 아닌 결정론적 샘플입니다.\n\n"
        f"요청 내용: {truncated_prompt}\n\n"
        f"이 응답은 Phase 0 Demo를 위해 미리 준비된 텍스트입니다. "
        f"실제 모델 추론 결과가 아닙니다."
    )

    return DemoResponse(
        model_id=model.id,
        text=sample_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_krw=round(cost_krw, 2),
        latency_ms=model.latency_ms,
        region=model.region,
        routing_reason=routing_reason,
    )


@dataclass(frozen=True)
class ApiKeyInfo:
    id: str
    label: str
    masked_key: str
    created_at: str
    status: str
    access_mode: str


DEMO_API_KEYS: list[ApiKeyInfo] = [
    ApiKeyInfo(
        id="key-001",
        label="개발 환경 테스트 키",
        masked_key="kap-demo-****-****-7f3a",
        created_at="2026-07-20 10:30",
        status="active",
        access_mode="business14-credit",
    ),
    ApiKeyInfo(
        id="key-002",
        label="BYOK 연동 키 (OpenAI)",
        masked_key="kap-byok-****-****-2c91",
        created_at="2026-07-22 14:15",
        status="active",
        access_mode="byok",
    ),
]

REVOKED_KEY_IDS: set[str] = set()


def mark_key_revoked(key_id: str) -> None:
    REVOKED_KEY_IDS.add(key_id)


def is_key_revoked(key_id: str) -> bool:
    return key_id in REVOKED_KEY_IDS


def generate_demo_key() -> ApiKeyInfo:
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return ApiKeyInfo(
        id="key-demo-new",
        label="Demo 생성 키",
        masked_key="kap-demo-****-****-a1b2",
        created_at=now,
        status="active",
        access_mode="business14-credit",
    )


@dataclass(frozen=True)
class AccessMode:
    id: str
    label: str
    description: str
    status: str


ACCESS_MODES: list[AccessMode] = [
    AccessMode(
        id="gateway",
        label="Gateway",
        description=(
            "Business 14 API가 외부 Provider로 요청을 전달합니다. "
            "고객은 하나의 API endpoint만 연동하면 됩니다."
        ),
        status="Demo 개념",
    ),
    AccessMode(
        id="byok",
        label="BYOK (Bring Your Own Key)",
        description=(
            "고객이 자기 Provider key를 사용하고 Business 14가 "
            "통합 관리·관측·라우팅 기능을 제공합니다."
        ),
        status="Demo 개념",
    ),
    AccessMode(
        id="business14-credit",
        label="Business 14 Credit",
        description=(
            "고객이 Business 14의 통합 credit으로 사용량을 결제하는 "
            "사업가설입니다. 실제 판매 또는 계약 완료 상태가 아닙니다."
        ),
        status="사업 가설",
    ),
    AccessMode(
        id="self-hosted",
        label="Self-hosted Inference",
        description=(
            "선정한 오픈모델을 향후 국내 또는 통제된 GPU 환경에서 "
            "직접 제공하는 확장가설입니다. 현재 GPU를 확보했거나 "
            "추론 서버가 운영 중이지 않습니다."
        ),
        status="확장 가설",
    ),
]


@dataclass(frozen=True)
class UsageRecord:
    timestamp: str
    model_id: str
    model_name: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_krw: float
    status: str
    latency_ms: int


DEMO_USAGE_RECORDS: list[UsageRecord] = [
    UsageRecord("2026-07-24 09:12", "openai-gpt4o", "GPT-4o", "OpenAI", 1200, 350, 5.1, "success", 920),
    UsageRecord("2026-07-24 09:08", "naver-hyperclova-x", "HyperCLOVA X", "Naver", 800, 200, 2.5, "success", 580),
    UsageRecord("2026-07-24 08:55", "anthropic-claude-sonnet", "Claude Sonnet 4", "Anthropic", 2500, 800, 26.0, "success", 1150),
    UsageRecord("2026-07-24 08:41", "kakao-kanana", "Kanana", "Kakao", 600, 150, 1.3, "success", 480),
    UsageRecord("2026-07-24 08:30", "openai-gpt4o", "GPT-4o", "OpenAI", 3000, 1200, 27.3, "error", 0),
    UsageRecord("2026-07-23 22:15", "google-gemini-pro", "Gemini 2.5 Pro", "Google", 1500, 600, 7.8, "success", 710),
    UsageRecord("2026-07-23 21:50", "ncsoft-varco", "VARCO LLM", "NCSoft", 400, 100, 0.9, "success", 430),
    UsageRecord("2026-07-23 21:30", "naver-hyperclova-x", "HyperCLOVA X", "Naver", 900, 250, 3.2, "success", 610),
]


@dataclass(frozen=True)
class UsageSummary:
    remaining_credit_krw: float
    monthly_requests: int
    monthly_cost_krw: float
    total_input_tokens: int
    total_output_tokens: int
    success_rate: float
    by_provider: list[dict]
    by_model: list[dict]


def compute_usage_summary() -> UsageSummary:
    total_in = sum(r.input_tokens for r in DEMO_USAGE_RECORDS)
    total_out = sum(r.output_tokens for r in DEMO_USAGE_RECORDS)
    total_cost = sum(r.cost_krw for r in DEMO_USAGE_RECORDS)
    success_count = sum(1 for r in DEMO_USAGE_RECORDS if r.status == "success")
    success_rate = success_count / len(DEMO_USAGE_RECORDS) * 100

    provider_map: dict[str, dict] = {}
    model_map: dict[str, dict] = {}
    for r in DEMO_USAGE_RECORDS:
        if r.provider not in provider_map:
            provider_map[r.provider] = {"provider": r.provider, "requests": 0, "cost_krw": 0.0, "tokens": 0}
        provider_map[r.provider]["requests"] += 1
        provider_map[r.provider]["cost_krw"] += r.cost_krw
        provider_map[r.provider]["tokens"] += r.input_tokens + r.output_tokens

        if r.model_name not in model_map:
            model_map[r.model_name] = {"model": r.model_name, "provider": r.provider, "requests": 0, "cost_krw": 0.0, "tokens": 0}
        model_map[r.model_name]["requests"] += 1
        model_map[r.model_name]["cost_krw"] += r.cost_krw
        model_map[r.model_name]["tokens"] += r.input_tokens + r.output_tokens

    return UsageSummary(
        remaining_credit_krw=42560.0,
        monthly_requests=len(DEMO_USAGE_RECORDS),
        monthly_cost_krw=round(total_cost, 1),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        success_rate=round(success_rate, 1),
        by_provider=sorted(provider_map.values(), key=lambda x: -x["cost_krw"]),
        by_model=sorted(model_map.values(), key=lambda x: -x["cost_krw"]),
    )


@dataclass(frozen=True)
class IntegrationExample:
    id: str
    label: str
    language: str
    code: str


def get_integration_examples(model_id: str = "openai-gpt4o") -> list[IntegrationExample]:
    model = MODELS_BY_ID.get(model_id, MODELS[0])
    return [
        IntegrationExample(
            id="curl",
            label="curl",
            language="bash",
            code=(
                'curl https://api.example-kap.demo/v1/chat/completions \\\n'
                '  -H "Authorization: Bearer $KAP_API_KEY" \\\n'
                '  -H "Content-Type: application/json" \\\n'
                "  -d '{\n"
                f'    "model": "{model.id}",\n'
                '    "messages": [\n'
                '      {"role": "user", "content": "안녕하세요"}\n'
                "    ]\n"
                "  }'"
            ),
        ),
        IntegrationExample(
            id="python",
            label="Python",
            language="python",
            code=(
                "import httpx\n"
                "\n"
                'response = httpx.post(\n'
                '    "https://api.example-kap.demo/v1/chat/completions",\n'
                '    headers={"Authorization": "Bearer $KAP_API_KEY"},\n'
                "    json={\n"
                f'        "model": "{model.id}",\n'
                '        "messages": [\n'
                '            {"role": "user", "content": "안녕하세요"}\n'
                "        ],\n"
                "    },\n"
                ")\n"
                "print(response.json())"
            ),
        ),
        IntegrationExample(
            id="javascript",
            label="JavaScript",
            language="javascript",
            code=(
                'const response = await fetch(\n'
                '  "https://api.example-kap.demo/v1/chat/completions",\n'
                "  {\n"
                '    method: "POST",\n'
                "    headers: {\n"
                '      Authorization: "Bearer $KAP_API_KEY",\n'
                '      "Content-Type": "application/json",\n'
                "    },\n"
                "    body: JSON.stringify({\n"
                f'      model: "{model.id}",\n'
                '      messages: [{ role: "user", content: "안녕하세요" }],\n'
                "    }),\n"
                "  }\n"
                ");\n"
                "const data = await response.json();\n"
                "console.log(data);"
            ),
        ),
        IntegrationExample(
            id="openai-compatible",
            label="OpenAI SDK 호환",
            language="python",
            code=(
                "from openai import OpenAI\n"
                "\n"
                "client = OpenAI(\n"
                '    base_url="https://api.example-kap.demo/v1",\n'
                '    api_key="$KAP_API_KEY",\n'
                ")\n"
                "\n"
                "response = client.chat.completions.create(\n"
                f'    model="{model.id}",\n'
                '    messages=[{"role": "user", "content": "안녕하세요"}],\n'
                ")\n"
                "print(response.choices[0].message.content)"
            ),
        ),
    ]
