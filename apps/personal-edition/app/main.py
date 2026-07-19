from fastapi import FastAPI
from app.config import settings

app = FastAPI(title="Personal Edition")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ai_provider": settings.ai_provider,
        "ai_model": settings.ai_model,
    }
