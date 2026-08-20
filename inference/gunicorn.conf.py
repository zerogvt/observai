"""Gunicorn configuration for the inference service.

Driven by environment variables so the *same image* behaves correctly across
local / staging / Kubernetes. Gunicorn auto-loads this with `-c gunicorn.conf.py`.
"""
import os

# Listen on all interfaces; PORT overridable (Kubernetes sets containerPort).
bind = f"0.0.0.0:{os.getenv('PORT', '8001')}"

# Worker count. The real throughput ceiling is Ollama, which serializes
# generation on your CPU/GPU — extra workers add request concurrency (queuing,
# not blocking /health) but won't make the model itself faster.
workers = int(os.getenv("WEB_CONCURRENCY", "4"))

# IMPORTANT: model calls are slow. The app's own OLLAMA_TIMEOUT_S (default 120s)
# is meant to fire first and return a clean 503. Gunicorn's worker timeout must
# therefore EXCEED that, or gunicorn will hard-kill the worker mid-generation
# (you'd see workers restarting and requests dying with no useful error). Hence
# the high default — keep it above OLLAMA_TIMEOUT_S.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "180"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# Do NOT preload. OpenTelemetry runs background export threads (both the
# BatchSpanProcessor and the PeriodicExportingMetricReader) that must be created
# inside each worker after the fork. preload_app=True imports the app in the
# master and forks, and those threads don't survive — silently breaking trace
# AND metric export. Leaving preload off gives each worker working exporters.
preload_app = False

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
