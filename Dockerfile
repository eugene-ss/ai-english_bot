# Stage 1: Сборка виртуального окружения через uv
FROM ghcr.io/astral-sh/uv:python3.11-alpine AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev

# Stage 2: Финальный продакшн образ
FROM python:3.11-alpine
WORKDIR /app

# Установка ffmpeg для конвертации аудиосообщений Telegram
RUN apk add --no-cache ffmpeg

COPY --from=builder /app/.venv /app/.venv
COPY config/ /app/config/
COPY images/ /app/images/
COPY locales/ /app/locales/
COPY src/ /app/src/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]