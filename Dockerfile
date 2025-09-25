# syntax=docker/dockerfile:1

# Use Python slim for smaller image
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Poetry for reproducible installs (project uses pyproject.toml)
ENV POETRY_VERSION=2.2.2
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Copy dependency files first for caching
COPY pyproject.toml poetry.lock /app/

# Configure Poetry to install to the system env (no virtualenv)
RUN poetry config virtualenvs.create false \
    && poetry install --without dev --no-interaction --no-ansi

# Copy application code
COPY . /app

# Expose default Django port
EXPOSE 8000

# Default to running Django via manage.py (override with CMD/args)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
