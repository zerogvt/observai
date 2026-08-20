# syntax=docker/dockerfile:1

# ---------- Stage 1: build dependencies into a venv ----------
FROM python:3.12-slim AS builder

WORKDIR /app

# Create an isolated venv we can copy wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install deps first (cached unless requirements.txt changes).
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt


# ---------- Stage 2: slim runtime image ----------
FROM python:3.12-slim AS runtime

# Run as a non-root user (Kubernetes-friendly, and good hygiene generally).
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

# Bring in the prebuilt venv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    WEB_CONCURRENCY=5

# Copy only what the service needs to run. Dev-only files (tests, mock_inference,
# .env, README) are excluded via .dockerignore and not copied here.
COPY app.py config.py tracing.py validation.py oversight.py gunicorn.conf.py ./

USER appuser

EXPOSE 8000

# Container-level healthcheck for `docker run` / compose. (Kubernetes ignores
# this and uses its own liveness/readiness probes against /health instead.)
# Uses Python's stdlib so we don't have to install curl.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# Production WSGI server. Config (port, workers, timeouts) comes from
# gunicorn.conf.py, which reads env vars — so Kubernetes can tune it without a
# rebuild.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
