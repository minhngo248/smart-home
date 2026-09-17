FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.source=https://github.com/minhngo248/smart-home

RUN useradd --no-create-home --shell /usr/sbin/nologin --uid 10001 kasa

COPY --from=builder /app/.venv /app/.venv
COPY tapo_control.py home.py agent.py api.py backend.py /app/

USER kasa
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH
ENV API_HOST=0.0.0.0
EXPOSE 8000
ENTRYPOINT ["python", "backend.py"]
