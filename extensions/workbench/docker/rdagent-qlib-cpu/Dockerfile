FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libgomp1 git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml setup.py README.md MANIFEST.in /src/
COPY qlib /src/qlib

ARG QLIB_VERSION=0.1.dev2068
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${QLIB_VERSION}
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir /src tables

WORKDIR /workspace/qlib_workspace
COPY workbench/quant_workbench /opt/qwb/quant_workbench
ENV PYTHONPATH=/opt/qwb
