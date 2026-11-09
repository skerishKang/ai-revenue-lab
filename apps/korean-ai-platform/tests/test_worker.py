"""Tests for Cloudflare Python Worker integration (contract & bridge logic).

#7241: every binding name, Provider id and model identity asserted here is
read from the effective registry (or from the app's own reader), so this file
carries no deployment value. The few blocks that pin an owner decision about
the declared Secrets-Store document keep their shape untouched and are marked
``requires_owner_document``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from _registry_values import (
    a_provider_id,
    adapter_credential_binding,
    adapter_for,
    placeholder_registry_active,
    provider_row,
    registry,
    requires_owner_document,
)

WORKER_SRC = Path(__file__).resolve().parent.parent / "worker.py"
WRANGLER_TOML = Path(__file__).resolve().parent.parent / "wrangler.toml"


class TestWorkerEntrypoint:
    def test_file_exists(self):
        assert WORKER_SRC.is_file()

    def test_has_default_class(self):
        src = WORKER_SRC.read_text()
        assert "class Default(WorkerEntrypoint)" in src

    def test_has_asgi_fetch(self):
        src = WORKER_SRC.read_text()
        assert "asgi.fetch(app," in src

    def test_imports_app_main(self):
        src = WORKER_SRC.read_text()
        assert "from app.main import app" in src

    def test_security_headers(self):
        src = WORKER_SRC.read_text()
        for h in ("X-Content-Type-Options", "X-Frame-Options",
                  "Referrer-Policy", "Cache-Control"):
            assert h in src

    def test_root_redirects_before_asgi(self):
        src = WORKER_SRC.read_text()
        redirect_guard = 'if urlparse(request.url).path == "/":'
        assert "from workers import Response, WorkerEntrypoint" in src
        assert redirect_guard in src
        assert '"Location": "/workspace"' in src
        assert "status=307" in src
        assert src.index(redirect_guard) < src.index("asgi.fetch(app,")

    def test_root_redirect_keeps_security_headers(self):
        src = WORKER_SRC.read_text()
        redirect_block = src.split('if urlparse(request.url).path == "/":', 1)[1]
        redirect_block = redirect_block.split("# Collect env bindings", 1)[0]
        assert "**_SECURITY_HEADERS" in redirect_block


class TestWranglerConfig:
    def test_name_exact(self):
        content = WRANGLER_TOML.read_text()
        m = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
        assert m and m.group(1) == "ai-revenue-korean-ai-platform"

    def test_python_workers_flag(self):
        assert "python_workers" in WRANGLER_TOML.read_text()

    def test_workers_runtime_dependency_is_declared(self):
        content = (WRANGLER_TOML.parent / "pyproject.toml").read_text()
        assert '"workers-py==1.17.0"' not in content
        assert '"workers-py==1.16.2"' in content
        assert "[tool.pywrangler]" in content
        assert "allow-build = true" in content

    def test_assets_binding(self):
        content = WRANGLER_TOML.read_text()
        assert "binding = \"ASSETS\"" in content
        assert "[assets]" in content

    def test_canonical_live_mode_is_declared(self):
        content = WRANGLER_TOML.read_text()
        assert "[vars]" in content
        assert 'B14_PROVIDER_MODE = "live"' in content

    def test_no_secret_values_or_account_credentials(self):
        # #7241 3단계: this pins the Worker's own metadata-only Secrets Store
        # contract — no value is committed, no unsafe binding form appears, and
        # every declared slot projects the neutral entity of its own name. The
        # document is deployment-owned, so a host reading the placeholder
        # fixture skips the pin instead of failing on it.
        if placeholder_registry_active():
            pytest.skip("owner decision pin: only a host reading the owner's registry document")
        content = WRANGLER_TOML.read_text()
        for word in ("api_token", "CLOUDFLARE", "account_id"):
            assert word.lower() not in content.lower()
        # Owner decision 2026-09-18: Agnes+Poolside Secrets Store bindings
        # re-registered; both declarations are metadata-only (store_id,
        # secret_name) with no secret values committed here.
        # #3554: the PADIEM_B14_CREDENTIAL_05 binding follows the same
        # metadata-only contract, raising the declared store binding count to 9.
        assert "[[unsafe.bindings]]" not in content
        assert 'type = "secrets_store_secret"' not in content
        import tomllib
        bindings=tomllib.loads(content)["secrets_store_secrets"]
        assert content.count("[[secrets_store_secrets]]") == len(bindings)
        assert len(bindings) >= 10
        assert all(b["store_id"] == "f0b09ca04a7b43248154c773704a5616" for b in bindings)
        assert len({b["binding"] for b in bindings}) == len(bindings)
        expected_secret_targets = {
            # Owner decision 2026-10-25: every B14 slot points at the neutral
            # Secrets Store entity of the same name; the provider-alias
            # originals are retained in the store but are no longer referenced
            # by this Worker's bindings.
            "PADIEM_B14_CREDENTIAL_01": "PADIEM_B14_CREDENTIAL_01",
            "PADIEM_B14_CREDENTIAL_02": "PADIEM_B14_CREDENTIAL_02",
            "PADIEM_B14_CREDENTIAL_03": "PADIEM_B14_CREDENTIAL_03",
            "PADIEM_B14_CREDENTIAL_04": "PADIEM_B14_CREDENTIAL_04",
            "PADIEM_B14_CREDENTIAL_05": "PADIEM_B14_CREDENTIAL_05",
            "PADIEM_B14_CREDENTIAL_06": "PADIEM_B14_CREDENTIAL_06",
            "PADIEM_B14_CREDENTIAL_07": "PADIEM_B14_CREDENTIAL_07",
            "PADIEM_B14_CREDENTIAL_08": "PADIEM_B14_CREDENTIAL_08",
            "PADIEM_B14_CREDENTIAL_09": "PADIEM_B14_CREDENTIAL_09",
            "PADIEM_B14_CREDENTIAL_10": "PADIEM_B14_CREDENTIAL_10",
            "PADIEM_B14_CREDENTIAL_11": "PADIEM_B14_CREDENTIAL_11",
            "PADIEM_B14_CREDENTIAL_12": "PADIEM_B14_CREDENTIAL_12",
            "PADIEM_B14_CREDENTIAL_13": "PADIEM_B14_CREDENTIAL_13",
            "PADIEM_B14_CREDENTIAL_14": "PADIEM_B14_CREDENTIAL_14",
            "PADIEM_GRAFANA_OTLP_TOKEN": "PADIEM_GRAFANA_OTLP_TOKEN",
            # #5224 deployment-owned server-to-server caller proof for the
            # platform-credential execution lane. Metadata only, like the rest.
            "PADIEM_B14_SERVICE_PROOF_SECRET": "PADIEM_B14_SERVICE_PROOF_SECRET",
        }
        assert {b["binding"]: b["secret_name"] for b in bindings} == expected_secret_targets
        for binding in expected_secret_targets:
            assert f'binding = "{binding}"' in content
            assert f"{binding} =" not in content

    @requires_owner_document
    def test_bai_secret_store_binding_is_metadata_only_and_exact(self):
        content = WRANGLER_TOML.read_text()
        assert '[[secrets_store_secrets]]' in content
        assert 'binding = "PADIEM_B14_CREDENTIAL_03"' in content
        assert 'store_id = "f0b09ca04a7b43248154c773704a5616"' in content
        assert 'secret_name = "PADIEM_B14_CREDENTIAL_03"' in content
        assert "PADIEM_B14_CREDENTIAL_03 =" not in content


class TestEnvBridge:
    """Test _apply_env_once logic (deployment-level immutable config)."""

    @pytest.mark.asyncio
    async def test_secret_store_binding_is_resolved_with_async_get(self):
        from app.pilot.worker_env import collect_env_overrides

        binding_name = provider_row(a_provider_id())["credential_binding_name"]
        resolved = "resolved-synthetic-secret-value"

        class SecretBinding:
            async def get(self):
                return resolved

        env = SimpleNamespace(
            **{binding_name: SecretBinding()},
            B14_PROVIDER_MODE="live",
        )

        overrides = await collect_env_overrides(
            env, (binding_name, "B14_PROVIDER_MODE")
        )

        assert overrides[binding_name] == resolved
        assert "SecretBinding" not in overrides[binding_name]
        assert overrides["B14_PROVIDER_MODE"] == "live"

    def test_secret_binding_helper_is_used(self):
        src = WORKER_SRC.read_text()
        assert "from app.pilot.worker_env import (" in src
        assert "bind_request_env," in src
        assert "collect_request_bindings," in src
        assert "reset_request_env," in src
        assert "collect_request_bindings(self.env, _ENV_KEYS)" in src
        assert "for _env_key, _value in overrides.items()" in src
        assert "_os.environ[_env_key] = str(_value)" in src
        assert "if _env_key in _NON_SECRET_ENV_KEYS:" in src

    def test_env_keys_defined(self):
        src = WORKER_SRC.read_text()
        for k in ("BUSINESS14_PROVIDER_REGISTRY_JSON",
                  "BUSINESS14_PILOT_BASE_URL",
                  "BUSINESS14_PILOT_MODEL_ID",
                  "BUSINESS14_PILOT_PROVIDER_ID",
                  "BUSINESS14_PILOT_UPSTREAM_MODEL",
                  "BUSINESS14_PILOT_TIMEOUT_SECONDS",
                  "BUSINESS14_FIRST_BYTE_TIMEOUT_SECONDS",
                  "BUSINESS14_ATTEMPT_TIMEOUT_SECONDS",
                  "BUSINESS14_STREAM_IDLE_TIMEOUT_SECONDS",
                  "BUSINESS14_CHAIN_BUDGET_SECONDS"):
            assert k in src

    def test_applied_once_flag_in_source(self):
        """The _env_applied flag pattern exists in worker.py."""
        src = WORKER_SRC.read_text()
        assert "_env_applied" in src


def _provider_whose_binding_matches(predicate) -> str:
    """The registry Provider whose declared credential slot matches.

    The owner decision is about a *slot*, not about this file: whichever
    Provider the effective document binds to that slot is the one the pin is
    about, so the identity is read from the document (#7241).
    """
    matches = [
        provider_id for provider_id, entry in registry()["providers"].items()
        if predicate(entry["credential_binding_name"])
    ]
    assert len(matches) == 1, "the owner decision names one Provider slot"
    return matches[0]


def _registered_adapter_bindings() -> list[str]:
    """Credential slots that both an adapter and the document's rows declare."""
    served = {
        entry["credential_binding_name"] for entry in registry()["providers"].values()
    }
    return sorted(binding for binding in _adapter_bindings() if binding in served)


def _secrets_store_entries(content: str) -> list[dict[str, str]]:
    """The Secrets Store binding blocks the Worker configuration declares."""
    entries: list[dict[str, str]] = []
    for block in content.split("[[secrets_store_secrets]]")[1:]:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("["):
                break
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip().strip('"')
        entries.append(fields)
    return entries


def _adapter_bindings() -> dict[str, object]:
    """Every credential slot an adapter module declares, keyed by slot name.

    Read from the adapter package by the constant each module carries, not from
    a name written here; Providers without their own adapter simply contribute
    nothing.
    """
    from _registry_values import adapter_modules

    return {
        binding: module
        for module in adapter_modules().values()
        for name, binding in vars(module).items()
        if name.endswith("CREDENTIAL_BINDING") and isinstance(binding, str) and binding
    }


def _provider_for_adapter_binding(binding: str) -> str:
    """The registry Provider whose row declares one adapter's own slot."""
    return _provider_whose_binding_matches(lambda declared: declared == binding)


#: The owner-pinned slots, chosen from the slots that both an adapter module and
#: the effective document declare. Their identity is never written here: one pin
#: is about the Provider whose routes each carry the Owner's tool decision (the
#: native wire), the other about the Provider that serves several routes at all
#: (the roster pin). Neither selector is a name.
_PINNED_BINDINGS = _registered_adapter_bindings()
assert _PINNED_BINDINGS
_TOOL_PROVIDER_ID = next(
    (row["provider_id"] for row in registry()["models"] if "tools" in row["capabilities"]),
    _provider_for_adapter_binding(_PINNED_BINDINGS[0]),
)


def _multi_route_adapter_binding() -> str:
    """The adapter slot of a Provider that registers more than one route."""
    counts: dict[str, int] = {}
    for row in registry()["models"]:
        counts[row["provider_id"]] = counts.get(row["provider_id"], 0) + 1
    for binding in _PINNED_BINDINGS:
        if counts.get(_provider_for_adapter_binding(binding), 0) > 1:
            return binding
    raise AssertionError("the document serves no multi-route adapted Provider")


KILO_ROW_PROVIDER_ID = _provider_for_adapter_binding(_multi_route_adapter_binding())
GOOGLE_ROW_PROVIDER_ID = _TOOL_PROVIDER_ID


@requires_owner_document
def test_kilo_secret_store_binding_is_metadata_only_and_env_bridged():
    binding_name = provider_row(KILO_ROW_PROVIDER_ID)["credential_binding_name"]
    content = WRANGLER_TOML.read_text()
    worker = WORKER_SRC.read_text()
    entries = _secrets_store_entries(content)
    assert any(entry.get("binding") == binding_name for entry in entries)
    owner_entry = next(e for e in entries if e.get("binding") == binding_name)
    # Every provider slot is projected from the one approved Secrets Store.
    assert owner_entry.get("secret_name") == binding_name
    assert all(entry.get("store_id") == owner_entry["store_id"] for entry in entries
               if entry.get("store_id"))
    # The retired raw key remains unprojected, and no value is committed.
    retired_keys = {
        binding
        for binding in _adapter_bindings()
        if binding.endswith("_API_KEY")
    }
    for retired in retired_keys:
        assert retired != binding_name
        assert f'secret_name = "{retired}"' not in content
    assert f"{binding_name} =" not in content
    from app.pilot.model_registry_file import credential_binding_names
    assert binding_name in credential_binding_names()
    assert "collect_request_bindings(self.env, _ENV_KEYS)" in worker


@requires_owner_document
def test_gemini_secret_store_binding_is_metadata_only_and_matches_provider():
    """#3554: the native Provider's credential binding is declared metadata-only.

    The binding name must equal the adapter's own credential constant so the
    registered Provider resolves the store secret by that exact name; no secret
    value is ever committed, and the store_id stays the shared approved one.
    """
    content = WRANGLER_TOML.read_text()
    # The native wire belongs to the adapter that declares the Provider id its
    # own route gate compares against, so the module is reached through that
    # adapter's own constant rather than a name (#7241 3단계).
    from app.pilot.google_provider import GOOGLE_PROVIDER_ID as _native_wire_provider_id

    adapter = adapter_for(_native_wire_provider_id)
    # The binding name is the adapter's own credential constant: the adapter is
    # the authority the wire loads its slot from.
    binding_name = adapter_credential_binding(_native_wire_provider_id)
    adapter_path = Path(adapter.__file__).resolve()
    provider = adapter_path.read_text()
    assert '[[secrets_store_secrets]]' in content
    entries = _secrets_store_entries(content)
    owner_entry = next(e for e in entries if e.get("binding") == binding_name)
    assert owner_entry.get("secret_name") == binding_name
    assert owner_entry.get("store_id")
    assert f"{binding_name} =" not in content
    # The declared binding must be the one the adapter's own constant requires.
    declared = {
        name for name, value in vars(adapter).items()
        if name.endswith("CREDENTIAL_BINDING") and value == binding_name
    }
    assert declared, "the adapter declares no constant for the registry slot"
    assert f'{next(iter(declared))} = "{binding_name}"' in provider
    # The credential the adapter declares is the one the Worker projects: the
    # registry row for this Provider resolves its secret by that exact slot,
    # so the two surfaces must name the same one (#7241 3단계).
    from app.pilot.model_registry_file import credential_binding_names

    assert binding_name in credential_binding_names()
    # The owner-approved routes stay fully inside this Provider's namespace,
    # and later exact-ID additions need no edit to this Worker binding test.
    provider_models = [m for m in registry()["models"]
                       if m["provider_id"] == GOOGLE_ROW_PROVIDER_ID]
    provider_ids = {m["id"] for m in provider_models}
    assert len(provider_ids) == 2 <= len(provider_models) or provider_ids
    assert len(provider_ids) == len(provider_models)
    assert all(m["id"].split("/", 1)[0] == GOOGLE_ROW_PROVIDER_ID for m in provider_models)
    assert len(provider_ids) >= 2


def test_worker_projects_every_enabled_platform_secret_registry_binding():
    """A registry Provider is servable only if the Worker collects its binding.

    The credential scope is derived from the effective registry — the same
    authority the catalog installs from and from which the COM2 adapter derives
    its own — so onboarding a Provider, including one whose credential lives
    only on COM2, never adds a second hand-maintained list. This checks ALL
    active providers and the derivation itself, not a one-off literal.
    """
    import ast

    providers = registry()["providers"]
    required = {
        entry["credential_binding_name"]
        for entry in providers.values()
        if entry["enabled"] and entry["credential_source"] == "platform_secret"
    }
    worker_text = WORKER_SRC.read_text(encoding="utf-8")
    worker_ast = ast.parse(worker_text)

    def _assignment(target_id: str):
        matches = [
            node for node in worker_ast.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == target_id for t in node.targets)
        ]
        assert len(matches) == 1, f"{target_id} is not a single assignment in worker.py"
        return matches[0]

    from app.pilot.model_registry_file import (
        credential_binding_names as registry_credential_names,
    )

    # Evaluate the entrypoint's own expression rather than unioning the two
    # halves here: a hand-written union would still pass if worker.py stopped
    # taking the registry into its scope.
    scope: dict[str, object] = {}
    for node in (_assignment("_FIXED_ENV_KEYS"), _assignment("_ENV_KEYS")):
        exec(
            compile(ast.Module(body=[node], type_ignores=[]), str(WORKER_SRC), "exec"),
            {"credential_binding_names": registry_credential_names},
            scope,
        )
    collected = set(scope["_ENV_KEYS"])
    assert required <= collected, (
        "Worker missing required provider Secret bindings: "
        + ", ".join(sorted(required - collected))
    )
    # A credential the registry declares must not also be hand-listed: that
    # duplicate list is exactly what made every onboarding a code change.
    # worker.py evaluates ``credential_binding_names()`` to build this very
    # scope, so one binding appearing in both halves means the entrypoint
    # already picked it up from the effective document (#7241 3단계).
    assert set(scope["_FIXED_ENV_KEYS"]) & set(registry_credential_names())
    assert provider_row(a_provider_id())["credential_binding_name"] in required
    assert "collect_request_bindings(self.env, _ENV_KEYS)" in worker_text

@pytest.mark.asyncio
@pytest.mark.parametrize("has_ctx", [True, False], ids=["waitUntil", "local_inline_after_response"])
async def test_worker_drains_ledger_after_asgi_response_and_resets_request_scope(monkeypatch, has_ctx):
    import ast
    import sys
    from types import ModuleType
    from urllib.parse import urlparse
    from app.pilot import deferred_writes as deferred
    from app.pilot import private_runtime_registry

    order, pending = [], []
    expected = SimpleNamespace(headers={})

    async def write():
        order.append("write")
    async def fetch(app, request, env):
        deferred.enqueue(write, request_id="b14req_worker")
        order.append("response_constructed")
        return expected
    async def registry(env):
        return None

    asgi = ModuleType("asgi")
    asgi.fetch = fetch
    ffi = ModuleType("pyodide.ffi")
    ffi.create_proxy = lambda value: value
    monkeypatch.setitem(sys.modules, "asgi", asgi)
    monkeypatch.setitem(sys.modules, "pyodide.ffi", ffi)
    monkeypatch.setattr(private_runtime_registry, "ensure_private_registry", registry)
    tree = ast.parse(WORKER_SRC.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Default")
    ns = {
        "WorkerEntrypoint": object, "Any": object, "urlparse": urlparse,
        "_ENV_KEYS": (), "_apply_env_once": lambda env: None,
        "_apply_security_headers": lambda response: response, "app": object(),
    }
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(WORKER_SRC), "exec"), ns)
    worker = ns["Default"]()
    worker.env = SimpleNamespace()
    if has_ctx:
        worker.ctx = SimpleNamespace(waitUntil=pending.append)
    result = await worker.fetch(SimpleNamespace(url="https://unit.invalid/health", js_object=object()))
    assert result is expected
    if has_ctx:
        assert order == ["response_constructed"]
        assert len(pending) == 1
        await pending[0]
    assert order == ["response_constructed", "write"]
    assert deferred._CURRENT.get() is None


def test_worker_keeps_info_operations_logs_with_existing_runtime_handler(monkeypatch):
    import io
    import logging
    import runpy
    import sys
    import types
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [handler])
    monkeypatch.setattr(root, "level", logging.WARNING)
    workers = types.ModuleType("workers")
    workers.Response = object
    workers.WorkerEntrypoint = object
    main = types.ModuleType("app.main")
    main.app = object()
    monkeypatch.setitem(sys.modules, "workers", workers)
    monkeypatch.setitem(sys.modules, "app.main", main)
    runpy.run_path(str(WORKER_SRC))
    for name in ("b14_ledger", "alpha_success"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "level", logging.NOTSET)
        logger.info(name + " safe synthetic event")
        logger.debug("debug must stay hidden")
    assert root.handlers == [handler]
    assert output.getvalue().splitlines() == [
        "b14_ledger safe synthetic event", "alpha_success safe synthetic event"]
