"""Entry point for uvicorn."""
from app.factory import create_app

app = create_app()