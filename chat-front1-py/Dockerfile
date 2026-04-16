FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY chat_front/ ./chat_front/

RUN uv pip install --system --no-cache .

CMD ["python", "-m", "chat_front.app"]
