"""Application configuration.

Reads KAP_-prefixed environment variables via os.environ.
Replaces pydantic-settings BaseSettings to avoid bundling
pydantic-core (4 MiB WASM binary) in Cloudflare Workers.
"""

from __future__ import annotations

import os


class Settings:
    app_name: str = "Korean AI Platform"
    demo_mode: bool = True

    def __init__(self) -> None:
        self.app_name = os.environ.get("KAP_APP_NAME", "Korean AI Platform")
        raw_demo = os.environ.get("KAP_DEMO_MODE", "true")
        self.demo_mode = raw_demo.lower() in ("true", "1", "yes")


settings = Settings()
