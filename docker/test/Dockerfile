# syntax=docker/dockerfile:1
FROM python:3.14-alpine
RUN apk add --no-cache git \
    && python -m pip install --no-cache-dir uv
RUN --mount=type=bind,from=depencity,target=/opt/depencity \
    uv pip install --system --no-cache /opt/depencity
WORKDIR /opt/agent-runner
COPY agent_runner/pyproject.toml agent_runner/README.md ./
COPY agent_runner/src ./src
RUN uv pip install --system --no-cache . 'pytest>=8' 'pytest-xdist>=3.6'
ENV PYTHONPATH="/workspace/agent_runner/src"
