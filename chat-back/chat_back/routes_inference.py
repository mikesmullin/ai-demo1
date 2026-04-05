"""Chat completions route — the core of chat-back."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from chat_back.auth import validate_token
from chat_back.models import ChatCompletionRequest, ChatCompletionResponse
from chat_back.providers import get_provider, parse_model_string
from chat_back.tracing import get_tracer

router = APIRouter(tags=["inference"])


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    claims: dict = Depends(validate_token),
):
    """OpenAI-compatible chat completions endpoint.

    Routes to the appropriate provider based on model prefix.
    """
    provider_key, model_name = parse_model_string(request.model)
    tracer = get_tracer()

    # GenAI semantic convention: span name = "{operation} {model}"
    with tracer.start_as_current_span(
        f"chat {model_name}",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": model_name,
            "gen_ai.provider.name": provider_key,
            "gen_ai.system": provider_key,
        },
    ) as span:
        try:
            provider = get_provider(provider_key)

            # Record request attributes
            span.set_attribute("server.address", provider.base_url)
            if request.temperature is not None:
                span.set_attribute("gen_ai.request.temperature", request.temperature)
            if request.top_p is not None:
                span.set_attribute("gen_ai.request.top_p", request.top_p)
            if request.max_tokens is not None:
                span.set_attribute("gen_ai.request.max_tokens", request.max_tokens)
            if request.tools:
                span.set_attribute(
                    "gen_ai.tool.definitions",
                    json.dumps([t.model_dump() for t in request.tools]),
                )

            # Record input messages (opt-in per spec, but useful for dev)
            span.set_attribute(
                "gen_ai.input.messages",
                json.dumps([m.model_dump(exclude_none=True) for m in request.messages]),
            )

            # Proxy to upstream provider
            response = await provider.chat_completion(request, model_name)

            # Record response attributes
            span.set_attribute("gen_ai.response.id", response.id)
            span.set_attribute("gen_ai.response.model", response.model)
            span.set_attribute("gen_ai.usage.input_tokens", response.usage.prompt_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", response.usage.completion_tokens)
            if response.choices:
                span.set_attribute(
                    "gen_ai.response.finish_reasons",
                    [c.finish_reason for c in response.choices],
                )
                span.set_attribute(
                    "gen_ai.output.messages",
                    json.dumps([c.message.model_dump(exclude_none=True) for c in response.choices]),
                )

            # Record user from JWT
            span.set_attribute("enduser.id", claims.get("sub", ""))

            return response

        except ValueError as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.set_attribute("error.type", "ValueError")
            raise HTTPException(400, str(e))
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.set_attribute("error.type", type(e).__name__)
            raise HTTPException(502, f"Upstream provider error: {e}")
