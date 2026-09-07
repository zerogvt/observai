# observAI Dynatrace dashboard

A Dynatrace **platform dashboard** (`version: 21`) built from the telemetry the observAI
services actually emit.

Two files, same dashboard, different envelopes — **pick the one that matches how you load it**:

| File | Use with | Shape |
|---|---|---|
| `observAI - AI Operations and Governance.json` | **UI upload** (Dashboards → Upload) | raw content: `version`, `variables`, `tiles`, `layouts`, `settings` at top level |
| `observai-ai-governance.document.json` | `dtctl apply`, Document API | envelope: `{ name, type, content: {...} }` |

Uploading the *envelope* file through the UI produces a dashboard with the right name and
**no tiles at all** — the UI reads `tiles`/`layouts` from the top level and finds nothing
there. If that is what you are looking at, upload the first file instead.

The UI takes the dashboard **name from the filename**, which is why that file is named the
way it is. Rename it before uploading if you want a different name.

One dashboard, three audiences:

| Section | Audience | Tiles |
|---|---|---|
| 1 · Executive summary | Managers | 6 KPIs + volume, tokens, task mix, latency trend |
| 2 · Governance & human oversight | Auditors | Review queue & rate, confidence distribution, flag reasons, completion reason, traceability gauge, model inventory, per-response audit table |
| 3 · Engineering & reliability | Engineers | Latency percentiles, gateway-vs-model hop split, tokens/sec, output-length vs latency scatter, failure modes, recent failures |

A single **`Task`** variable (multi-select: `chat, summarize, classify, extract`) filters
every data tile. No time ranges are hardcoded — the dashboard's time-frame picker drives
everything.

---

## Loading it into your tenant

### Option A — UI (no tooling needed)

1. Open your Dynatrace tenant → **Dashboards**.
2. **Upload** and pick **`observAI - AI Operations and Governance.json`** — the raw-content
   file, *not* the `.document.json` one.

### Option B — `dtctl`

```bash
export DT_ENVIRONMENT="https://<env-id>.apps.dynatrace.com"
export DT_PLATFORM_TOKEN="dt0s16.XXXX.XXXX"     # or use dtctl's OAuth login

dtctl apply -f observai-ai-governance.document.json -o yaml --dry-run   # validate first
dtctl apply -f observai-ai-governance.document.json -o yaml             # deploy
```

`dtctl apply` runs schema + DQL validation before writing, and prints the dashboard URL.
This is also the fastest way to find out which tile queries fail, if any.

> **Note:** `dtctl apply` deletes the local file on success. Commit it, or copy it aside first.

### If tiles are still missing after uploading the right file

Two things to check, in order:

1. **Schema version.** `version: 21` is recent. If your tenant runs an older Dashboards app,
   it may ignore the document. Open any existing dashboard, **Download** it, and look at its
   `version` — then set the same number in the file's top-level `version` field.
2. **A single tile.** Create a blank dashboard in the UI, add one Data tile, paste
   `timeseries requests = sum(observai.inference.requests)`, and see whether it returns
   anything. That separates "the dashboard document is wrong" from "the telemetry is not
   in Grail under these names" — the verification queries below cover the second case.

### Updating later

Never re-upload either file over a dashboard someone has edited in the UI. Download the
server's current state, edit that, and re-apply:

```bash
dtctl get dashboard <id> -o json --plain > current.json
# edit current.json (it carries the `id`)
dtctl apply -f current.json -o yaml
```

---

## Telemetry the dashboard reads

Everything below is emitted by this repo — nothing is invented.

### Metrics (OTLP → collector → Dynatrace), from `inference/tracing.py`

| Metric key | Type | Dimensions | Source |
|---|---|---|---|
| `observai.tokens.in` | counter | `task`, `model` | `inference/app.py` |
| `observai.tokens.out` | counter | `task`, `model` | `inference/app.py` |
| `observai.inference.latency` | histogram (ms) | `task`, `model` | `inference/app.py` |
| `observai.inference.requests` | counter | `task`, `model`, `outcome` | `inference/app.py` |

The collector's `cumulativetodelta` processor converts these to delta temporality, which is
why every metric tile uses `sum(...)` rather than a rate.

### Span attributes

**`gateway.handle_prompt`** (`gateway/app.py`) — the end-to-end span:
`ai.task`, `ai.input.chars`, `request.id`, `observai.tokens.in`, `observai.tokens.out`,
`observai.cost.usd`, `observai.model`, `observai.confidence`, `ai.oversight.flagged`,
`ai.oversight.reasons`, and on failure `error.kind` ∈ {`inference_timeout`,
`inference_unavailable`}.

**`inference.generate`** (`inference/app.py`) — the model call:
`ai.task`, `ai.model`, `request.id`, `ai.tokens.in`, `ai.tokens.out`, `ai.latency.ms`,
`ai.tokens_per_sec`, `ai.confidence`, `ai.needs_review`, `ai.done_reason`, and on failure
`error.kind` = `ollama_unavailable`.

---

## Verify before you trust the tiles

These queries were written against the source, **not executed against a tenant** — there was
no `DT_ENVIRONMENT` configured in the session that produced them. Run these three checks in
a notebook first; they tell you immediately whether the field names survived ingest.

**1 · Are the metrics arriving under these keys?**

```dql
metrics
| filter startsWith(metric.key, "observai.")
| summarize count(), by: { metric.key }
```

Expect four rows. If they are missing, the collector is not exporting metrics — check the
`observai-otel-collector` pod logs for the `debug` exporter summary.

**2 · Did the custom span attributes survive?**

```dql
fetch spans, from: -2h
| filter in(span.name, { "gateway.handle_prompt", "inference.generate" })
| summarize {
    spans            = count(),
    has_task         = countIf(isNotNull(ai.task)),
    has_confidence   = countIf(isNotNull(ai.confidence)),
    has_flag         = countIf(isNotNull(ai.oversight.flagged)),
    has_reasons      = countIf(isNotNull(ai.oversight.reasons)),
    has_done_reason  = countIf(isNotNull(ai.done_reason)),
    has_tokens_out   = countIf(isNotNull(ai.tokens.out)),
    has_tps          = countIf(isNotNull(ai.tokens_per_sec)),
    has_error_kind   = countIf(isNotNull(error.kind)),
    has_request_id   = countIf(isNotNull(request.id))
  }, by: { span.name }
```

Any `has_*` column sitting at 0 while `spans` is non-zero means that attribute was dropped
or renamed at ingest, and the tiles that use it will be blank.

**3 · Is the latency histogram queryable as an average?**

```dql
timeseries avg_ms = avg(observai.inference.latency)
```

Dynatrace converts OTLP explicit-bucket histograms into summary statistics. `avg`, `min`,
`max`, `sum` and `count` are reliable; **percentiles over this metric are not**, which is why
the engineering section derives p50/p95/p99 from span `duration` instead.

---

## Known caveats in the current instrumentation

Three things surfaced while reading the code. None of them break the dashboard as written,
but two are worth fixing in the services.

**1 · `request.id` collides with a reserved Dynatrace span field.**
`request.id` is a first-class field on Grail spans (OneAgent request correlation). The
gateway and inference services set an OTel attribute of the same name. If Dynatrace
prefers its own field, the `request_id` column in the audit table and the traceability
gauge will show nulls even though the attribute was sent. **Fix:** rename the attribute to
`observai.request.id` in `gateway/app.py` and `inference/app.py`, then update the three
tiles that reference it (ids `19`, `22`, `29`). Verification query 2 above tells you
whether this is actually a problem in your tenant.

**2 · The error path drops the `model` dimension.**
In `inference/app.py`, the failure branch emits
`requests_counter.add(1, {"task": task, "outcome": "error"})` — no `model`. The success
branch includes it. Any future tile that filters `observai.inference.requests` by `model`
will silently exclude every error and report a success rate of 100%. The success-rate tile
here deliberately avoids filtering by model for exactly this reason. **Fix:** add
`"model": Config.OLLAMA_MODEL` to the error-path attributes.

**3 · The attribute names are custom, not OpenTelemetry GenAI semantic conventions.**
Dynatrace's built-in **AI Observability** app keys off `gen_ai.*` — `gen_ai.request.model`,
`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.response.finish_reasons`, `gen_ai.operation.name`. observAI uses `ai.*` /
`observai.*`, so none of that built-in tooling lights up and this dashboard has to read the
raw spans. Emitting the `gen_ai.*` names **in addition to** the existing ones (a handful of
extra `set_attribute` calls) would give you the whole native AI Observability experience —
model/provider topology, token analytics, guardrail views — for free, alongside this
dashboard. `ai.done_reason` maps almost exactly onto `gen_ai.response.finish_reasons`
(`stop` / `length`).

---

## Adjusting the dashboard

**Confidence bands (tile `16`)** are cut at 0.2 / 0.4 / **0.6** / 0.8. The 0.6 boundary is
the review floor from `inference/k8s/observai-inference.yaml`
(`CONFIDENCE_REVIEW_FLOOR: "0.6"`) and `gateway` `OVERSIGHT_CONFIDENCE_FLOOR: "0.6"`. Note
the code *defaults* differ (`0.7` in `inference/config.py`) — if you deploy without the
manifests, retune the band labels.

**Making `Task` dynamic.** The variable is a static CSV list matching
`ALLOWED_TASKS`. To have it discover tasks from live data instead, replace the variable
block with:

```json
{
  "version": 2, "key": "Task", "type": "query",
  "visible": true, "editable": true,
  "input": "fetch spans | filter isNotNull(ai.task) | filter ai.task != \"\" | dedup ai.task | fields ai.task | sort ai.task asc",
  "multiple": true,
  "defaultValue": "3420b2ac-f1cf-4b24-b62d-61ba1ba8ed05*"
}
```

A query variable must return at least one row or the dashboard is considered invalid — so
only switch once traffic is flowing.

**Turning tiles into alerts.** The two best candidates are the human-review rate (tile `7`)
and success rate (tile `3`). Both are single-value DQL — drop them into a metric-events
anomaly detector with a static threshold, or into a workflow on a schedule.
