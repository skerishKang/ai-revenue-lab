"""#4139: production factory reuses the existing canonical TXT Broker route."""
import pytest

from kagent.contracts import ContractError
from kagent.local_agent_production_request_port import (
    PRODUCTION_BROKER_AUTHORITY,
    PRODUCTION_BROKER_OPERATION_PATHS,
    build_production_request_port,
    build_production_transport_config,
    production_broker_url,
    verify_operation_path_mapping,
)


def test_production_port_routes_are_canonical():
    config = build_production_transport_config()
    routes = verify_operation_path_mapping(build_production_request_port(), config)
    assert len(routes) == len(PRODUCTION_BROKER_OPERATION_PATHS) == 7
    assert routes["text-result"].endswith("/text-result")
    assert not any(path.endswith("/file-result") for path in routes.values())
    assert config.endpoint.url == production_broker_url()


def test_cannot_override_authority_or_mount():
    for mount in ("//evil.example/", "/a/../gateway", "/path?host=evil", "http://evil"):
        with pytest.raises(ContractError):
            build_production_transport_config(mount_path=mount)
    assert PRODUCTION_BROKER_AUTHORITY == "chat.padiem.net"


def test_canonical_device_route_matches_broker_source():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    source = (root / "packages" / "padiem-control-plane" / "local_agent_broker_text_results.py").read_text(encoding="utf-8")
    assert 'TEXT_RESULT_DEVICE_ROUTE = "/text-result"' in source
