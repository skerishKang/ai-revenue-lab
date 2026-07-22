"""Run the Personal Video Archive application."""

from __future__ import annotations

import uvicorn

from app.factory import create_app

app = create_app()


def main() -> None:
    """Run the application with uvicorn."""
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
