FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN uv pip install --system --no-cache python-kasa>=0.7.7

FROM python:3.12-slim-bookworm

# Run as non-root
RUN useradd --no-create-home --shell /sbin/nologin kasa

# Copy only the installed packages and the kasa binary
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/kasa /usr/local/bin/kasa

USER kasa