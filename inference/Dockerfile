# syntax=docker/dockerfile:1

# ---------- Stage 1: build dependencies into a venv ----------
FROM python:3.12-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt


# ---------- Stage 2: slim runtime image ----------
FROM python:3.12-slim AS runtime

# Non-root user (Kubernetes pod security standards often require runAsNonRoot).
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8001 \
    WEB_CONCURRENCY=4

# Copy only runtime modules. Dev-only files (tests, fake_ollama, .env, README)
# are excluded via .dockerignore.
COPY app.py config.py tracing.py prompts.py provider.py confidence.py gunicorn.conf.py ./

USER appuser

EXPOSE 8001

# Container-level healthcheck for `docker run` / compose. Kubernetes uses its
# own probes against /health instead. /health returns 200 as long as the Flask
# app is up (it reports Ollama reachability in the body but doesn't fail on it),
# which is the right behavior for a liveness check.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
