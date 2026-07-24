"""Tests for all routes in the API Provider Phase 0 Demo."""

from __future__ import annotations

from app.demo_data import MODELS, get_available_models


class TestCoreRoutes:
    def test_home_renders(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "한국 개발자를 위한 하나의 AI API" in resp.text

    def test_models_renders(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        assert "모델 카탈로그" in resp.text

    def test_playground_renders(self, client):
        resp = client.get("/playground")
        assert resp.status_code == 200
        assert "API Playground" in resp.text

    def test_api_keys_renders(self, client):
        resp = client.get("/api-keys")
        assert resp.status_code == 200
        assert "API 키 관리" in resp.text

    def test_usage_renders(self, client):
        resp = client.get("/usage")
        assert resp.status_code == 200
        assert "사용량 및 크레딧" in resp.text

    def test_docs_renders(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "API 문서" in resp.text

    def test_access_renders(self, client):
        resp = client.get("/access")
        assert resp.status_code == 200
        assert "이용 방법" in resp.text

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["phase"] == "api-provider-phase0"

    def test_not_found(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404


class TestModelCatalog:
    def test_all_models_rendered(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        available = get_available_models()
        for model in available:
            assert model.name in resp.text

    def test_filter_external(self, client):
        resp = client.get("/models?type=external")
        assert resp.status_code == 200
        assert "GPT-4o" in resp.text
        assert "HyperCLOVA" not in resp.text

    def test_filter_domestic(self, client):
        resp = client.get("/models?type=domestic")
        assert resp.status_code == 200
        assert "HyperCLOVA" in resp.text
        assert "GPT-4o" not in resp.text

    def test_filter_open_model(self, client):
        resp = client.get("/models?type=open-model")
        assert resp.status_code == 200
        assert "오픈모델" in resp.text or "전용 추론" in resp.text

    def test_model_detail_renders(self, client):
        model = MODELS[0]
        resp = client.get(f"/models/{model.id}")
        assert resp.status_code == 200
        assert model.name in resp.text

    def test_invalid_model_id_404(self, client):
        resp = client.get("/models/nonexistent")
        assert resp.status_code == 404


class TestPlayground:
    def test_playground_get(self, client):
        resp = client.get("/playground")
        assert resp.status_code == 200
        assert "Prompt" in resp.text

    def test_playground_post_with_prompt(self, client):
        resp = client.post("/playground", data={
            "prompt": "안녕하세요",
            "model_id": "openai-gpt4o",
            "routing_mode": "direct",
        })
        assert resp.status_code == 200
        assert "Mock Response" in resp.text or "Mock response" in resp.text

    def test_playground_post_empty_prompt(self, client):
        resp = client.post("/playground", data={
            "prompt": "",
            "model_id": "openai-gpt4o",
            "routing_mode": "direct",
        })
        assert resp.status_code == 200
        assert "Mock Response" not in resp.text

    def test_playground_routing_cheapest(self, client):
        resp = client.post("/playground", data={
            "prompt": "테스트",
            "routing_mode": "cheapest",
        })
        assert resp.status_code == 200
        assert "Mock Response" in resp.text or "Mock response" in resp.text

    def test_playground_routing_fastest(self, client):
        resp = client.post("/playground", data={
            "prompt": "테스트",
            "routing_mode": "fastest",
        })
        assert resp.status_code == 200
        assert "Mock Response" in resp.text or "Mock response" in resp.text

    def test_playground_routing_korean_first(self, client):
        resp = client.post("/playground", data={
            "prompt": "테스트",
            "routing_mode": "korean-first",
        })
        assert resp.status_code == 200
        assert "Mock Response" in resp.text or "Mock response" in resp.text

    def test_playground_routing_domestic_first(self, client):
        resp = client.post("/playground", data={
            "prompt": "테스트",
            "routing_mode": "domestic-first",
        })
        assert resp.status_code == 200
        assert "Mock Response" in resp.text or "Mock response" in resp.text

    def test_playground_prompt_preserved(self, client):
        prompt = "이것은 테스트 prompt입니다"
        resp = client.post("/playground", data={
            "prompt": prompt,
            "model_id": "openai-gpt4o",
            "routing_mode": "direct",
        })
        assert resp.status_code == 200
        assert prompt in resp.text

    def test_playground_result_shows_metadata(self, client):
        resp = client.post("/playground", data={
            "prompt": "안녕",
            "model_id": "openai-gpt4o",
            "routing_mode": "direct",
        })
        assert resp.status_code == 200
        assert "Input tokens" in resp.text
        assert "Output tokens" in resp.text
        assert "예상 비용" in resp.text
        assert "예상 latency" in resp.text
        assert "처리 위치" in resp.text
        assert "Routing reason" in resp.text


class TestApiKeys:
    def test_api_keys_renders(self, client):
        resp = client.get("/api-keys")
        assert resp.status_code == 200
        assert "발급된 API 키" in resp.text

    def test_api_key_create_redirect(self, client):
        resp = client.post("/api-keys/create", follow_redirects=False)
        assert resp.status_code == 303
        assert "created=1" in resp.headers["location"]

    def test_api_key_revoke_redirect(self, client):
        resp = client.post("/api-keys/key-001/revoke", follow_redirects=False)
        assert resp.status_code == 303
        assert "revoked=key-001" in resp.headers["location"]

    def test_access_modes_displayed(self, client):
        resp = client.get("/api-keys")
        assert resp.status_code == 200
        assert "Gateway" in resp.text
        assert "BYOK" in resp.text
        assert "Business 14 Credit" in resp.text
        assert "Self-hosted" in resp.text

    def test_demo_key_label_present(self, client):
        resp = client.get("/api-keys")
        assert resp.status_code == 200
        assert "Demo" in resp.text


class TestUsage:
    def test_usage_renders(self, client):
        resp = client.get("/usage")
        assert resp.status_code == 200
        assert "남은 Demo 크레딧" in resp.text

    def test_usage_shows_credit(self, client):
        resp = client.get("/usage")
        assert resp.status_code == 200
        assert "원" in resp.text

    def test_usage_shows_provider_breakdown(self, client):
        resp = client.get("/usage")
        assert resp.status_code == 200
        assert "Provider별 사용량" in resp.text

    def test_usage_shows_model_breakdown(self, client):
        resp = client.get("/usage")
        assert resp.status_code == 200
        assert "모델별 사용량" in resp.text

    def test_usage_shows_recent_requests(self, client):
        resp = client.get("/usage")
        assert resp.status_code == 200
        assert "최근 API 요청" in resp.text

    def test_usage_shows_success_rate(self, client):
        resp = client.get("/usage")
        assert resp.status_code == 200
        assert "성공률" in resp.text


class TestDocs:
    def test_docs_renders(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "curl" in resp.text
        assert "Python" in resp.text
        assert "JavaScript" in resp.text

    def test_docs_model_selection(self, client):
        resp = client.get("/docs?model=openai-gpt4o")
        assert resp.status_code == 200
        assert "openai-gpt4o" in resp.text

    def test_docs_shows_placeholder_key(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "$KAP_API_KEY" in resp.text

    def test_docs_shows_demo_endpoint(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "example-kap.demo" in resp.text

    def test_docs_openai_compatible(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "OpenAI SDK 호환" in resp.text


class TestAccess:
    def test_access_renders(self, client):
        resp = client.get("/access")
        assert resp.status_code == 200
        assert "이용 방법" in resp.text

    def test_access_shows_all_modes(self, client):
        resp = client.get("/access")
        assert resp.status_code == 200
        assert "Gateway" in resp.text
        assert "BYOK" in resp.text
        assert "Business 14 Credit" in resp.text
        assert "Self-hosted" in resp.text


class TestTruthfulness:
    def test_no_ai_working_message(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "AI가 작업하고 있습니다" not in resp.text

    def test_no_task_template_language(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "무엇을 AI에게 맡기고 싶으세요" not in resp.text

    def test_demo_label_present(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Demo" in resp.text

    def test_no_real_provider_claim(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "실제 API 호출" not in resp.text

    def test_no_secret_in_source(self, client):
        resp = client.get("/api-keys")
        assert resp.status_code == 200
        assert "sk-" not in resp.text
        assert "Bearer " not in resp.text

    def test_demo_endpoint_not_real(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "example-kap.demo" in resp.text
        assert "api.openai.com" not in resp.text

    def test_no_real_payment_claim(self, client):
        resp = client.get("/usage")
        assert resp.status_code == 200
        assert "실제 결제" not in resp.text

    def test_no_real_customer_claim(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "실제 고객" not in resp.text


class TestNavigation:
    def test_nav_links_present(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'href="/"' in resp.text
        assert 'href="/models"' in resp.text
        assert 'href="/playground"' in resp.text
        assert 'href="/api-keys"' in resp.text
        assert 'href="/usage"' in resp.text
        assert 'href="/docs"' in resp.text
        assert 'href="/access"' in resp.text

    def test_no_workspace_language(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "사용자 화면" not in resp.text
        assert "운영자 화면" not in resp.text

    def test_brand_subtitle_is_provider(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "AI API Provider" in resp.text

    def test_no_model_settings_nav(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "모델·보안 설정" not in resp.text


class TestP0FixApiKeyCreateCTA:
    def test_create_cta_is_post_form(self, client):
        resp = client.get("/api-keys")
        assert resp.status_code == 200
        assert 'method="post"' in resp.text
        assert '/api-keys/create' in resp.text
        assert 'a href="/api-keys/create"' not in resp.text

    def test_create_cta_method_contract(self, client):
        resp = client.get("/api-keys/create")
        assert resp.status_code in (405, 404)

    def test_create_post_redirects(self, client):
        resp = client.post("/api-keys/create", follow_redirects=False)
        assert resp.status_code == 303
        assert "created=1" in resp.headers["location"]


class TestP0FixKeyState:
    def test_create_shows_new_row(self, client):
        resp = client.get("/api-keys?created=1")
        assert resp.status_code == 200
        assert "Demo 생성 키" in resp.text
        assert "active" in resp.text

    def test_revoke_changes_target(self, client):
        resp = client.get("/api-keys?revoked=key-001")
        assert resp.status_code == 200
        assert "revoked" in resp.text
        assert "key-001" in resp.text

    def test_revoke_other_key_unchanged(self, client):
        resp = client.get("/api-keys?revoked=key-001")
        assert resp.status_code == 200
        assert "key-002" in resp.text

    def test_invalid_key_revoke_no_success(self, client):
        resp = client.get("/api-keys?invalid=1")
        assert resp.status_code == 200
        assert "유효하지 않은 키 ID" in resp.text
        assert "새 키 생성" in resp.text

    def test_invalid_key_post_no_success(self, client):
        resp = client.post("/api-keys/nonexistent/revoke", follow_redirects=False)
        assert resp.status_code == 303
        assert "invalid=1" in resp.headers["location"]


class TestAllModelsAvailable:
    def test_all_8_models_in_catalog(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        from app.demo_data import MODELS
        for model in MODELS:
            assert model.name in resp.text, f"Model {model.name} not in catalog"

    def test_ko_open_in_catalog(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        assert "Ko-Open 32B" in resp.text

    def test_llama_ko_in_catalog(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        assert "Llama-Ko 70B" in resp.text

    def test_all_8_models_in_playground(self, client):
        resp = client.get("/playground")
        assert resp.status_code == 200
        from app.demo_data import MODELS
        for model in MODELS:
            assert model.id in resp.text, f"Model {model.id} not in playground"

    def test_ko_open_playground_response(self, client):
        resp = client.post("/playground", data={
            "prompt": "test",
            "model_id": "selfhost-ko-open",
            "routing_mode": "direct",
        })
        assert resp.status_code == 200
        assert "Mock Response" in resp.text or "Mock response" in resp.text

    def test_llama_ko_playground_response(self, client):
        resp = client.post("/playground", data={
            "prompt": "test",
            "model_id": "selfhost-llama-ko",
            "routing_mode": "direct",
        })
        assert resp.status_code == 200
        assert "Mock Response" in resp.text or "Mock response" in resp.text

    def test_routing_policies_valid_models(self, client):
        from app.demo_data import ROUTING_POLICIES, MODELS_BY_ID
        for policy in ROUTING_POLICIES:
            assert policy.selected_model_id in MODELS_BY_ID

    def test_no_fallback_for_valid_model(self, client):
        resp = client.get("/playground?model=selfhost-ko-open")
        assert resp.status_code == 200
        assert 'value="selfhost-ko-open"' in resp.text
        assert "selected" in resp.text

    def test_model_detail_ko_open(self, client):
        resp = client.get("/models/selfhost-ko-open")
        assert resp.status_code == 200
        assert "Ko-Open 32B" in resp.text
        assert "Playground에서 시험하기" in resp.text

    def test_model_detail_llama_ko(self, client):
        resp = client.get("/models/selfhost-llama-ko")
        assert resp.status_code == 200
        assert "Llama-Ko 70B" in resp.text

    def test_docs_all_models_selectable(self, client):
        from app.demo_data import MODELS
        for model in MODELS:
            resp = client.get(f"/docs?model={model.id}")
            assert resp.status_code == 200
            assert model.id in resp.text

    def test_home_shows_8_models(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "8" in resp.text

    def test_pricing_route(self, client):
        resp = client.get("/pricing")
        assert resp.status_code == 200
        assert "요금 구조" in resp.text
        assert "예시 요금 구조" in resp.text

    def test_global_disclaimer_present(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "제휴" in resp.text or "재판매" in resp.text

    def test_no_unavailable_messaging(self, client):
        resp = client.get("/models/selfhost-ko-open")
        assert resp.status_code == 200
        assert "사용할 수 없습니다" not in resp.text
        assert "준비 중" not in resp.text
        assert "미리보기만" not in resp.text


class TestP1FixPlaygroundModel:
    def test_playground_model_query_preserved(self, client):
        resp = client.get("/playground?model=openai-gpt4o")
        assert resp.status_code == 200
        assert 'value="openai-gpt4o"' in resp.text
        assert "selected" in resp.text

    def test_playground_invalid_model_fallback(self, client):
        resp = client.get("/playground?model=nonexistent")
        assert resp.status_code == 200

    def test_playground_available_model_selected(self, client):
        resp = client.get("/playground?model=naver-hyperclova-x")
        assert resp.status_code == 200
        assert 'value="naver-hyperclova-x"' in resp.text
        assert "selected" in resp.text


class TestP1FixCopyTargets:
    def test_docs_copy_targets_exist(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        for example_id in ("curl", "python", "javascript", "openai-compatible"):
            assert f'id="code-{example_id}"' in resp.text

    def test_docs_copy_btn_has_data_copy_target(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "data-copy-target" in resp.text

    def test_model_detail_no_copy_btn_without_target(self, client):
        resp = client.get("/models/openai-gpt4o")
        assert resp.status_code == 200
        assert "data-copy-target" not in resp.text


class TestP1FixHomeWording:
    def test_home_shows_model_count(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "8" in resp.text

    def test_home_no_realtime_claim(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "실시간" not in resp.text

    def test_home_model_cards_have_demo_label(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Demo" in resp.text


class TestP2Gitignore:
    def test_gitignore_exists(self):
        from pathlib import Path
        gitignore = Path(__file__).resolve().parent.parent / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert "__pycache__" in content

