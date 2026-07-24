"""Tests for all routes in the API Provider Phase 0 Demo."""

from __future__ import annotations

from app.demo_data import MODELS


class TestCoreRoutes:
    def test_home_renders(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "여러 AI 모델을 하나의 API로" in resp.text

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
        for model in MODELS:
            assert model.name in resp.text

    def test_filter_external(self, client):
        resp = client.get("/models?type=external")
        assert resp.status_code == 200
        assert "OpenAI" in resp.text
        assert "Naver" not in resp.text

    def test_filter_domestic(self, client):
        resp = client.get("/models?type=domestic")
        assert resp.status_code == 200
        assert "Naver" in resp.text
        assert "OpenAI" not in resp.text

    def test_filter_self_hosted(self, client):
        resp = client.get("/models?type=self-hosted")
        assert resp.status_code == 200
        assert "자체 호스팅" in resp.text

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
        assert "Demo 응답 결과" in resp.text
        assert "Demo 데이터" in resp.text

    def test_playground_post_empty_prompt(self, client):
        resp = client.post("/playground", data={
            "prompt": "",
            "model_id": "openai-gpt4o",
            "routing_mode": "direct",
        })
        assert resp.status_code == 200
        assert "Demo 응답 결과" not in resp.text

    def test_playground_routing_cheapest(self, client):
        resp = client.post("/playground", data={
            "prompt": "테스트",
            "routing_mode": "cheapest",
        })
        assert resp.status_code == 200
        assert "Demo 응답 결과" in resp.text

    def test_playground_routing_fastest(self, client):
        resp = client.post("/playground", data={
            "prompt": "테스트",
            "routing_mode": "fastest",
        })
        assert resp.status_code == 200
        assert "Demo 응답 결과" in resp.text

    def test_playground_routing_korean_first(self, client):
        resp = client.post("/playground", data={
            "prompt": "테스트",
            "routing_mode": "korean-first",
        })
        assert resp.status_code == 200
        assert "Demo 응답 결과" in resp.text

    def test_playground_routing_domestic_first(self, client):
        resp = client.post("/playground", data={
            "prompt": "테스트",
            "routing_mode": "domestic-first",
        })
        assert resp.status_code == 200
        assert "Demo 응답 결과" in resp.text

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
        assert "처리 지역" in resp.text
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
        assert "revoked=1" in resp.headers["location"]

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
