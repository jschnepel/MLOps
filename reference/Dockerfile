# Reference image. Pin the resolved base digest after your first verified build.
FROM python:3.13-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip wheel --wheel-dir=/wheels '.[web]'

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPS_DATA_DIR=/app/runtime APP_MODE=reference
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels 'operations-copilot[web]'     && rm -rf /wheels     && groupadd --gid 10001 app     && useradd --uid 10001 --gid 10001 --no-create-home app     && mkdir /app/runtime && chown 10001:10001 /app/runtime
COPY --chown=10001:10001 scripts ./scripts
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "operations_copilot.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
