# Image unique de l'ITSM : serveur web (par défaut) et worker
# (`python manage.py procrastinate worker`).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.3 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 itsm
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY manage.py ./
COPY src ./src
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=itsm.settings.prod
RUN DJANGO_SECRET_KEY=collectstatic-only AZURE_STORAGE_ACCOUNT_NAME=build \
    python manage.py collectstatic --noinput
USER itsm
EXPOSE 8000
CMD ["gunicorn", "--chdir", "src", "--bind", "0.0.0.0:8000", "--workers", "3", "itsm.wsgi"]
