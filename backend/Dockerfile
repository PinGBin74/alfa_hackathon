FROM python:3.12.12-slim-bookworm

# uv 0.9 читает uv.lock формата revision 3; старые версии его не понимают
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

WORKDIR /app

# Зависимости строго по uv.lock: если lock не совпадает с pyproject.toml, сборка падает
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
