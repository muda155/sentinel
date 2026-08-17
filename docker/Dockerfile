FROM python:3.14-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# Mount the pip HTTP cache into the build so wheel re-downloads are skipped
# when this layer re-runs (requirements.txt change / build-cache prune). The
# cache lives in Docker's build cache, not the image.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY . .
# Default command is the API; compose overrides `command:` per worker service.
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
