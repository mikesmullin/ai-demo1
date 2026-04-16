FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml ./
COPY oauth_idp/ ./oauth_idp/

# Install dependencies
RUN uv pip install --system --no-cache .

EXPOSE 9000

CMD ["uvicorn", "oauth_idp.app:app", "--host", "0.0.0.0", "--port", "9000"]
