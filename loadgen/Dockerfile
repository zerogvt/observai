# syntax=docker/dockerfile:1

# ---------- Stage 1: build deps into a venv ----------
FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ---------- Stage 2: slim runtime ----------
FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY config.py conversation.py loadgen.py ./
USER appuser
# No EXPOSE / HEALTHCHECK: this is a worker that generates traffic, not a server.
CMD ["python", "loadgen.py"]
