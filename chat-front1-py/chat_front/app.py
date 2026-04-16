"""chat-front — headless Pydantic AI agent.

On startup, runs one inference + tool-call loop through Envoy AI Gateway,
logs every step to stdout, then idles. Restart the pod to trigger another run.
"""

from __future__ import annotations

import asyncio
import signal
import sys
import time

from openai import AsyncOpenAI
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from chat_front.agent import agent
from chat_front.config import Settings


def _log(stage: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{stage}] {msg}", flush=True)


async def run_once(settings: Settings) -> None:
    """Execute one full inference + tool-call loop."""
    envoy = settings.envoy_base_url
    _log("INIT", f"Envoy base URL: {envoy}")
    _log("INIT", f"Model: {settings.envoy_model}")
    _log("INIT", f"Prompt: {settings.user_prompt}")

    # OpenAI-compatible client pointing at Envoy AI Gateway
    openai_client = AsyncOpenAI(
        base_url=f"{envoy}/v1",
        api_key="not-needed",  # API key is injected by Envoy's BackendSecurityPolicy
        default_headers={"x-ai-eg-model": settings.envoy_model},
    )
    provider = OpenAIProvider(openai_client=openai_client)
    model = OpenAIChatModel(settings.envoy_model, provider=provider)

    # MCP toolset — connects to Envoy's aggregated /mcp endpoint
    mcp_server = MCPServerStreamableHTTP(f"{envoy}/mcp")

    _log("RUN", "Starting agent run...")

    async with mcp_server:
        result = await agent.run(
            settings.user_prompt,
            model=model,
            toolsets=[mcp_server],
        )

    _log("RESULT", f"Agent reply: {result.output}")

    # Log the full message history for observability
    _log("TRACE", "--- Message history ---")
    for i, msg in enumerate(result.all_messages()):
        _log("TRACE", f"  [{i}] {msg.kind}: {msg}")
    _log("TRACE", "--- End ---")
    _log("DONE", "Run complete. Pod idling.")


def main() -> None:
    settings = Settings()

    try:
        asyncio.run(run_once(settings))
    except Exception as e:
        _log("ERROR", f"{type(e).__name__}: {e}")
        sys.exit(1)

    # Idle forever — restart the pod to trigger another run
    _log("IDLE", "Sleeping. Restart pod to run again.")
    evt = asyncio.Event()
    signal.signal(signal.SIGTERM, lambda *_: evt.set())
    signal.signal(signal.SIGINT, lambda *_: evt.set())
    try:
        asyncio.run(evt.wait())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
