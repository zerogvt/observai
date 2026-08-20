"""Gunicorn configuration for the gateway.

Driven entirely by environment variables so the *same image* behaves correctly
in local / staging / Kubernetes without rebuilds. Gunicorn auto-loads this file
when started with `-c gunicorn.conf.py`.
"""
import os

# Listen on all interfaces; PORT is overridable (Kubernetes sets containerPort).
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Worker count. Default 2; override with WEB_CONCURRENCY.
# NOTE: the in-memory rate limiter is per-worker, so with >1 worker (or >1 pod)
# the limit is enforced per worker, not globally. For correct global rate
# limiting set the app's RATE_LIMIT_STORAGE_URI to a redis:// URL.
workers = int(os.getenv("WEB_CONCURRENCY", "2"))

timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# IMPORTANT: do NOT preload the app.
# OpenTelemetry's BatchSpanProcessor runs a background export thread that must
# be created *inside each worker* (after the fork). With preload_app=True the
# app is imported in the master and then forked, and that thread does not
# survive the fork — silently breaking trace export. Leaving preload off means
# each worker imports the app itself and gets its own working exporter.
preload_app = False

# Log access + errors to stdout/stderr so Kubernetes/Docker captures them.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
