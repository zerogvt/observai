# OTel Collector → Dynatrace

Receives OTLP from the gateway and inference services and forwards traces +
metrics to Dynatrace. The apps stay backend-agnostic (they just export to
`localhost:4318`); this is the only piece that knows about Dynatrace.

```
gateway ─┐
         ├─OTLP/HTTP→ Collector (:4318) ──auth──→ Dynatrace
inference┘
```

## 1. Get your Dynatrace details

- **Endpoint:** your environment's OTLP base URL.
  - SaaS: `https://<env-id>.live.dynatrace.com/api/v2/otlp`
  - Managed: `https://<your-domain>/e/<env-id>/api/v2/otlp`
  - The `<env-id>` is the alphanumeric string in your Dynatrace URL.
- **API token:** Dynatrace → Settings → Access Tokens → Generate new token,
  with the OTLP ingest scopes (`openTelemetryTrace.ingest`, `metrics.ingest`).
  Exact scope labels vary a little by Dynatrace version — match by meaning.

**Security:** the token is a credential. Put it only in `.env`, never in code
or git. `cp .env.example .env`, fill it in, and make sure `.env` is gitignored.
(Don't paste the token into a chat or anywhere else, either.)

## 2. Run the Collector

```bash
cp .env.example .env     # then edit in your endpoint + token
docker compose up        # foreground so you can watch the logs
```

Check it's healthy: `curl -s localhost:13133` should return 200.

## 3. Point the apps at it

In each service's `.env`:

```
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

That's the only change — no code edits. Start the gateway + inference as
usual, send a few `/prompt` requests, and watch the Collector logs: the
`debug` exporter prints a one-line summary of each batch of spans/metrics it
forwards. That tells you data is leaving the Collector before you even open
Dynatrace.

## 4. Verify in Dynatrace

- **Traces:** Distributed Traces / Services — look for `service.name`
  `gateway` and `inference`, and the `gateway → inference` call chain.
- **Metrics:** Data Explorer / Metrics — search for `observai.tokens.in`,
  `observai.tokens.out`, `observai.inference.latency`, `observai.inference.requests`.
- Allow up to ~10s: metrics export on a 10s interval, so they lag slightly.

## Gotchas baked into the config

- **Delta temporality.** Dynatrace expects DELTA temporality for OTLP metrics;
  the OTel SDK default is CUMULATIVE. The `cumulativetodelta` processor in the
  metrics pipeline converts it. (This is why we use the **contrib** Collector
  image — the core image lacks that processor.)
- **`debug` vs `logging`.** The console-summary exporter is named `debug` in
  recent Collector versions and `logging` in older ones. If startup complains
  about an unknown exporter `debug`, rename it to `logging` in the config.
- **`Api-Token ` prefix.** The Authorization header value must be literally
  `Api-Token <token>` — the prefix and the space matter.

## No-Collector alternative

You can skip the Collector and export straight to Dynatrace by setting the
apps' `OTEL_EXPORTER_OTLP_ENDPOINT` to your Dynatrace OTLP base URL and adding
the `Authorization: Api-Token ...` header to the exporters in `tracing.py`.
It's fewer moving parts, but it puts the token in the app and you lose the
batching/decoupling/temporality handling above — so the Collector is the
recommended path.
