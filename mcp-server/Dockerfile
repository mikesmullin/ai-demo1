FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml ./
COPY mcp_server/ ./mcp_server/

# Install dependencies
RUN uv pip install --system --no-cache .

EXPOSE 8200

CMD ["uvicorn", "mcp_server.app:app", "--host", "0.0.0.0", "--port", "8200"]
