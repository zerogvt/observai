# observAI Dynatrace dashboard

A Dynatrace **platform dashboard** built from the telemetry the observAI
services emit.

| Section | Audience | Tiles |
|---|---|---|
| 1 · Executive summary | Managers | 6 KPIs + volume, tokens, task mix, latency trend |
| 2 · Governance & human oversight | Auditors | Review queue & rate, confidence distribution, flag reasons, completion reason, traceability gauge, model inventory, per-response audit table, flagged-chat prompt/reply records |
| 3 · Engineering & reliability | Engineers | Latency percentiles, gateway-vs-model hop split, tokens/sec, output-length vs latency scatter, failure modes, recent failures |

## Data sources

Most tiles read `timeseries` metrics or `fetch spans`. One reads `fetch logs`:
**"Flagged chats — what was actually asked and answered"** queries the audit
sink (`audit.event.type == "observai.oversight.audit"`) for the prompt and
reply text, which spans deliberately never carry. It sits directly under the
span-based "Flagged responses — audit record" tile so an auditor can go from
the verdict to the content; both share `request_id`. Sampling is switched off
on that tile on purpose — a partially sampled audit table still reads as
complete. See the README's "Audit records" section for the field list.
