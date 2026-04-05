"""OTEL tracing setup for mcp-gw."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from mcp_gw.config import settings


def setup_tracing() -> None:
    """Initialize OTEL tracing with OTLP gRPC exporter."""
    resource = Resource.create({
        "service.name": settings.otel_service_name,
        "service.version": "0.1.0",
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint, insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("mcp-gw", "0.1.0")
