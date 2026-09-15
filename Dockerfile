# syntax=docker/dockerfile:1
#
# Two images from one file:
#   * default (stage "ingestion") — the `msl` CLI, used by `docker compose run ingestion`
#   * stage "research"            — same code + JupyterLab/DuckDB for local exploration
#
# uv is copied in from its official image (pinned to the version that wrote uv.lock),
# dependencies are installed in a layer *before* the source is copied so that editing
# code never re-downloads packages.

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.14 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MSL_DATA_DIR=/app/data
COPY pyproject.toml uv.lock ./

FROM base AS ingestion
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY README.md ./
RUN uv sync --frozen --no-dev
VOLUME ["/app/data"]
ENTRYPOINT ["msl"]
CMD ["--help"]

FROM base AS research
RUN uv sync --frozen --group research --no-install-project
COPY src ./src
COPY README.md ./
RUN uv sync --frozen --group research
EXPOSE 8888
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", \
     "--ServerApp.token=", "--ServerApp.password="]
