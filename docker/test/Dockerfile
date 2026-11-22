# syntax=docker/dockerfile:1
FROM python:3.14-alpine
RUN apk add --no-cache git build-base linux-headers libunwind-dev lz4-dev pkgconf elfutils-dev \
    && python -m pip install --no-cache-dir uv
RUN uv pip install --system --no-cache depencity
WORKDIR /opt/agent-runner
COPY agent_runner/pyproject.toml agent_runner/README.md ./
COPY agent_runner/src ./src
RUN uv pip install --system --no-cache . 'pytest>=8' 'pytest-xdist>=3.6' 'pytest-benchmark>=5.2' 'pytest-memray>=1.8' pytest-cov
ENV PYTHONPATH="/workspace/agent_runner/src"
