FROM ghcr.io/astral-sh/uv:trixie-slim AS builder

ENV UV_PYTHON_INSTALL_DIR=/python UV_PYTHON_CACHE_DIR=/root/.cache/uv/python
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_PREFERENCE=only-managed

RUN uv python install 3.12

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project


FROM gcr.io/distroless/python3-debian13

LABEL org.opencontainers.image.title="Discord to Keycloak Role Sync"
LABEL org.opencontainers.image.description="Synchronises membership of Discord roles to Keycloak groups"
LABEL org.opencontainers.image.authors="Ike Johnson-Woods <contact@ike.au>"

LABEL org.opencontainers.image.source=https://github.com/NotActuallyTerry/discord-keycloak-rolesync
LABEL org.opencontainers.image.license=MPL-2.0

COPY --from=builder /python /python
COPY --from=builder /app /app

COPY app.py /app/app.py
WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "app.py"]