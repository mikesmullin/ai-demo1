"""chat-front — FastAPI app exposing a chat endpoint powered by Pydantic AI.

Routes:
  GET  /health      — health check
  POST /chat        — send a message, get agent response
  GET  /login       — start OAuth login (redirects to IDP)
  GET  /callback    — OAuth callback (exchanges code for token)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pydantic_ai.mcp import MCPServerStreamableHTTP

from chat_front.agent import Deps, agent
from chat_front.config import Settings
from chat_front.oauth import get_token_via_pkce, register_client

settings = Settings()

# Stores the IDP-assigned client_id after registration
_registered_client_id: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _registered_client_id
    # Register this app as OAuth client on startup (best-effort)
    try:
        result = await register_client(
            settings.idp_url,
            settings.client_id,
            settings.client_secret,
            settings.redirect_uri,
        )
        _registered_client_id = result.get("client_id")
    except Exception:
        pass  # IDP may not be running during tests
    yield


app = FastAPI(
    title="chat-front",
    version="0.1.0",
    description="Pydantic AI agent chat frontend",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Chat ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    access_token: str | None = None


class ChatResponse(BaseModel):
    reply: str


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the AI agent and get a response."""
    deps = Deps(access_token=req.access_token or "")

    # Point pydantic-ai at chat-back
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        base_url=f"{settings.chat_back_url}/v1",
        api_key=req.access_token or "no-token",
    )
    model_name = settings.default_model.split(":", 1)[-1] if ":" in settings.default_model else settings.default_model
    model = OpenAIChatModel(model_name, provider=provider)

    # Native MCP toolset — connects to mcp-gw via Streamable HTTP
    # Pass the user's OAuth token so mcp-gw can authenticate + attribute tool calls
    mcp_toolset = MCPServerStreamableHTTP(
        f"{settings.mcp_gw_url}/mcp",
        headers={"Authorization": f"Bearer {req.access_token}"} if req.access_token else None,
    )

    result = await agent.run(req.message, deps=deps, model=model, toolsets=[mcp_toolset])
    return ChatResponse(reply=result.output)


# ── OAuth convenience endpoints ──────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Perform PKCE login and return access token."""
    try:
        # Use the IDP-assigned client_id if available
        effective_client_id = _registered_client_id or settings.client_id
        tokens = await get_token_via_pkce(
            idp_url=settings.idp_url,
            client_id=effective_client_id,
            client_secret=settings.client_secret,
            redirect_uri=settings.redirect_uri,
            username=req.username,
            password=req.password,
        )
        return LoginResponse(access_token=tokens["access_token"])
    except Exception as e:
        raise HTTPException(400, f"Login failed: {e}")
