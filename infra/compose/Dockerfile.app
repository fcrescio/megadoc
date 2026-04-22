FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/appuser \
    XDG_CACHE_HOME=/home/appuser/.cache \
    HF_HOME=/home/appuser/.cache/huggingface \
    PYTHONPATH=/app/packages/common/src:/app/services/api/src:/app/services/worker/src:/app/services/cli/src

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
RUN mkdir -p /home/appuser/.cache/huggingface /usr/local/lib/python3.11/site-packages/rapidocr/models \
    && chown -R appuser:appuser /home/appuser /usr/local/lib/python3.11/site-packages/rapidocr/models

COPY . .
USER appuser
