"""chat-back FastAPI application — AI inference proxy."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from chat_back.routes_inference import router as inference_router
from chat_back.tracing import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing()
    yield


app = FastAPI(
    title="chat-back",
    version="0.1.0",
    description="AI inference proxy — OpenAI-compatible API routing to multiple providers",
    lifespan=lifespan,
)

app.include_router(inference_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
def list_models():
    """Return available provider prefixes."""
    return {
        "object": "list",
        "data": [
            {"id": "xai:grok-3", "object": "model", "owned_by": "xai"},
            {"id": "copilot:claude-sonnet-4.6", "object": "model", "owned_by": "copilot"},
        ],
    }
