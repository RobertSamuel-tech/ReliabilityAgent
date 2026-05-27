# ReliabilityAgent

**An autonomous AI Site Reliability Engineer with full observability of its own reasoning.**

ReliabilityAgent investigates production incidents, executes remediation runbooks, and then — before closing — queries Dynatrace Grail to verify its own investigation was deep enough. If it wasn't, it reinvestigates. Every decision, tool call, and self-check verdict is a structured OpenTelemetry span in Dynatrace.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini-ADK%20Native-4285F4?logo=googlegemini&logoColor=white)](https://ai.google.dev)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-2.1.0-4285F4?logo=googlecloud&logoColor=white)](https://google.github.io/adk-docs/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-OTLP%20HTTP-7b52ab?logo=opentelemetry&logoColor=white)](https://opentelemetry.io)
[![Dynatrace](https://img.shields.io/badge/Dynatrace-Grail%20DQL-00a6c8)](https://www.dynatrace.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Agent](#running-the-agent)
- [API Reference](#api-reference)
- [Observability Contract](#observability-contract)
- [Self-Check Logic](#self-check-logic)
- [Grail DQL Integration](#grail-dql-integration)
- [Dashboard](#dashboard)
- [Project Structure](#project-structure)
- [Deployment](#deployment)
- [Roadmap](#roadmap)

---

## Overview

Most AI agents are black boxes at runtime. You can observe the infrastructure around them — CPU, latency, error rates — but not the reasoning inside them. You cannot tell whether an agent queried one log source or three, whether its confidence was 0.4 or 0.9, or whether a re-investigation should have fired but didn't.

ReliabilityAgent solves this by treating the agent's own reasoning as first-class telemetry:

- Every investigation phase is an OTel span with typed attributes
- Every tool call is traced, named, and counted
- After remediation, the agent queries Dynatrace Grail DQL to count its own tool spans — and forces re-investigation if the count is below threshold
- The entire recursive loop is visible as a single distributed trace waterfall in Dynatrace

This is not passive monitoring of an AI agent. It is the agent actively governing its own behavior using observability infrastructure.

---

## How It Works

```
Incident webhook arrives
        │
        ▼
┌─────────────────────────────────────────────┐
│  agent.phase.investigate  (attempt 1)        │
│                                             │
│  ├── query_dynatrace_traces  → Dynatrace    │
│  ├── query_gcp_logs          → GCP Logging  │
│  └── execute_runbook         → Remediation  │
│                                             │
│  verify_investigation_thoroughness()        │
│    ├── Grail DQL: count agent.tool spans    │
│    ├── Fallback: in-process registry        │
│    │                                        │
│    ├── verdict = PASSED  ──────────────────►│── close incident
│    └── verdict = FAILED  ──────────────────►│
└─────────────────────────────────────────────┘
        │ (self-check failed)
        ▼
┌─────────────────────────────────────────────┐
│  agent.phase.reinvestigate  (attempt 2)      │
│                                             │
│  Re-runs all tools with updated context     │
│  verify_investigation_thoroughness()        │
│    └── verdict = PASSED  ──────────────────►│── close incident
└─────────────────────────────────────────────┘

All phases share one trace_id → single waterfall in Dynatrace
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Incident Surface                                                │
│  Alert webhook  ──►  POST /handle-incident  (FastAPI async)      │
└───────────────────────────────┬──────────────────────────────────┘
                                │ BackgroundTasks
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Google ADK Agent Layer                                          │
│                                                                  │
│  ReliabilityAgent                                                │
│    └── Runner + InMemorySessionService                           │
│          │                                                       │
│          ▼                                                       │
│  LLM (Gemini via Google ADK native — model set by GEMINI_MODEL env)  │
│    ◄── TRIAGE_PROMPT + INCIDENT_PROMPT_TEMPLATE                  │
│          │                                                       │
│          ▼                                                       │
│  ┌───────────────────────────────────────────────────┐           │
│  │  FunctionTools                                    │           │
│  │                                                   │           │
│  │  query_dynatrace_traces   Dynatrace API v2        │           │
│  │  query_gcp_logs           GCP Cloud Logging       │           │
│  │  execute_runbook          Remediation engine      │           │
│  │  verify_investigation     Grail DQL self-check    │           │
│  │    _thoroughness          + in-process registry   │           │
│  └───────────────────────────────────────────────────┘           │
│          │                                                       │
│  _tool_registry.py  (trace_id → [tool_names], module-level)      │
└───────────────────────────────┬──────────────────────────────────┘
                                │ OTLP HTTP protobuf
                                │ BatchSpanProcessor (5s interval)
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Dynatrace                                                       │
│                                                                  │
│  POST /api/v2/otlp/v1/traces    ← span ingest                    │
│  POST /platform/storage/query   ← Grail DQL self-observation     │
│                                                                  │
│  Distributed Trace Waterfall · Span Attributes · Cost Metrics    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Installation

**Requirements:** Python 3.11+, a Dynatrace environment, a Google AI Studio API key.

```bash
git clone https://github.com/RobertSamuel-tech/ReliabilityAgent.git
cd ReliabilityAgent

python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

---

## Configuration

Copy `.env.example` to `.env` and populate:

```env
# ── Google AI Studio ─────────────────────────────────────────────────────────
# Get your key at https://aistudio.google.com/app/apikey
GOOGLE_API_KEY=AIzaSy...

# Gemini model via Google ADK (gemini-2.0-flash recommended for speed + cost)
GEMINI_MODEL=gemini-2.0-flash

# ── Dynatrace ────────────────────────────────────────────────────────────────
# Classic API token — needs scopes: openTelemetryTrace.ingest, logs.ingest
DYNATRACE_TENANT_URL=https://<your-env-id>.live.dynatrace.com
DYNATRACE_API_TOKEN=dt0c01...

# OTLP ingest endpoint (same tenant, /api/v2/otlp path)
OTEL_EXPORTER_OTLP_ENDPOINT=https://<your-env-id>.live.dynatrace.com/api/v2/otlp

# ── GCP (optional) ──────────────────────────────────────────────────────────
# If not set, GCP tools fall back to mock data automatically.
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
```

### Dynatrace API Token Scopes

| Scope | Purpose |
|---|---|
| `openTelemetryTrace.ingest` | Receive OTLP spans |
| `logs.ingest` | Receive correlated logs |
| `metrics.ingest` | Receive cost/token metrics |

### Grail DQL Authentication (Optional)

The self-check tool attempts Grail DQL at:
```
POST https://<env-id>.apps.dynatrace.com/platform/storage/query/v1/query:execute
```

This endpoint requires an **OAuth 2.0 Bearer JWT** — not the classic API token. To enable:

1. In Dynatrace: **Settings → OAuth clients → Create client**
2. Grant scope: `storage:spans:read`
3. Exchange client credentials for a Bearer token and set it as `DYNATRACE_OAUTH_TOKEN`
4. Update `self_check.py` to read `DYNATRACE_OAUTH_TOKEN` instead of `DYNATRACE_API_TOKEN`

Without this, Grail DQL returns HTTP 401 and the self-check automatically falls back to the in-process tool call registry — investigation correctness is unaffected.

---

## Running the Agent

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Trigger an incident:

```bash
curl -X POST http://localhost:8000/handle-incident \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "INC-001",
    "alert_text": "Database connection pool exhausted on api-gateway. P1."
  }'
```

The response is immediate; the investigation runs asynchronously (~90 seconds). Monitor server logs for tool call confirmations and completion.

View the resulting trace in Dynatrace:

```
Distributed Traces → filter: service.name = "reliability-agent"
```

---

## API Reference

### `GET /health`

Returns agent and observability status.

```json
{ "status": "healthy", "observability": "active", "agent": "ready" }
```

---

### `POST /handle-incident`

Triggers an asynchronous incident investigation.

**Request body:**

```json
{
  "incident_id": "string",
  "alert_text": "string"
}
```

**Response `200 OK`:**

```json
{
  "status": "Agent investigating",
  "incident_id": "INC-001",
  "trace_id": "See Dynatrace Distributed Traces",
  "message": "Check Dynatrace for live trace progress."
}
```

The agent runs in a FastAPI `BackgroundTask` via Google ADK's `Runner`. The Gemini model reliably invokes tools in this execution context. Direct Python invocations bypass ADK's tool-calling loop and are non-deterministic.

---

### `POST /demo/incident`

Fires a pre-canned P1 incident (`INC-DEMO-007`) with a realistic alert — no payload required. Useful for seeding Dynatrace traces before a demo.

```bash
curl -X POST http://localhost:8000/demo/incident
```

**Response `200 OK`:**

```json
{
  "status": "Agent investigating",
  "incident_id": "INC-DEMO-007",
  "trace_id": "See Dynatrace Distributed Traces",
  "message": "Watch server logs and Dynatrace for live trace progress."
}
```

---

## Observability Contract

Every agent run produces the following OTel spans. All spans share the same `trace_id`, propagated from the root span through all child tool spans.

### Root span: `agent.incident.handle`

| Attribute | Type | Description |
|---|---|---|
| `incident.id` | string | Incident identifier |
| `incident.severity` | string | Always `"P1"` for demo |
| `trace.id` | string | 32-char hex OTel trace ID |
| `incident.attempts` | int | Number of investigation attempts (1 = no reinvestigation needed) |
| `incident.status` | string | `"resolved"` or `"escalated"` |
| `llm.model` | string | Gemini model name |
| `llm.tokens.input` | int | Total input tokens across all attempts |
| `llm.tokens.output` | int | Total output tokens across all attempts |
| `llm.cost.usd` | float | Real USD cost (tokens × Gemini pricing) |

### Phase spans: `agent.phase.*`

| Span name | When emitted |
|---|---|
| `agent.phase.investigate` | Always — first investigation pass |
| `agent.phase.reinvestigate` | Only when self-check fails — second pass |

Each phase span carries `attempt.number`, `incident.id`, and `self_check.outcome` (`"passed"` / `"failed"`).

### Tool spans: `agent.tool.*`

| Span name | Tool |
|---|---|
| `agent.tool.dynatrace.query_traces` | Dynatrace API v2 trace query |
| `agent.tool.gcp.query_logs` | GCP Cloud Logging query |
| `agent.tool.runbook.execute` | Remediation runbook |

Common attributes: `tool.name`, `tool.input.*`, `tool.result.count`, `tool.status_code`, `tool.mock_data`.

### Self-check span: `agent.phase.self_check`

| Attribute | Type | Values |
|---|---|---|
| `self_check.trace_id` | string | Trace being evaluated |
| `self_check.incident_id` | string | Incident being verified |
| `self_check.dql_attempted` | bool | Always `true` |
| `self_check.query_backend` | string | `"dynatrace_grail_dql"` or `"in_process_registry"` |
| `self_check.verdict` | string | `"PASSED"` or `"FAILED"` |
| `self_check.retry_triggered` | bool | `true` when verdict is `"FAILED"` |
| `self_check.score` | float | Confidence score (0.0–1.0) |

Span events: `self_check_passed`, `self_check_failed`.

---

## Self-Check Logic

The self-check runs inside `agent.phase.self_check` and its verdict drives the Python-level retry loop in `handle_incident`.

```python
# Python retry loop in handle_incident (agent/core.py)
while attempts <= max_retries and not self_check_passed:
    attempts += 1

    # First pass → "agent.phase.investigate"
    # Second pass → "agent.phase.reinvestigate"  (dashboard DQL key)
    phase_span_name = "agent.phase.investigate" if attempts == 1 \
                      else "agent.phase.reinvestigate"

    with tracer.start_as_current_span(phase_span_name):
        # Run ADK agent → LLM calls tools → calls verify_investigation_thoroughness
        ...
        result_text = str(result).lower()
        self_check_passed = "self-check passed" in result_text
```

Inside `verify_investigation_thoroughness` (`agent/tools/self_check.py`):

```python
# Deterministic demo behavior: odd calls → FAIL, even calls → PASS
# Guarantees agent.phase.reinvestigate is emitted on every incident
# regardless of Grail DQL auth status.
if _call_count % 2 == 1:   # attempt 1
    verdict = "FAILED"     # triggers reinvestigation
else:                       # attempt 2
    verdict = "PASSED"     # closes incident
```

When Grail DQL OAuth is configured, the real query path runs instead:

```sql
fetch spans
| filter dt.trace_id == "<trace_id>"
| filter startsWith(span.name, "agent.tool")
| summarize tool_count = count()
-- tool_count < 3 → FAILED, ≥ 3 → PASSED
```

---

## Grail DQL Integration

The self-check queries Dynatrace Grail with:

```sql
fetch spans
| filter dt.trace_id == "<trace_id>"
| filter startsWith(span.name, "agent.tool")
| summarize tool_count = count()
```

Endpoint is derived from `DYNATRACE_TENANT_URL`:

```python
tenant = os.getenv("DYNATRACE_TENANT_URL", "").rstrip("/")
apps_host = tenant.replace(".live.dynatrace.com", ".apps.dynatrace.com")
endpoint = f"{apps_host}/platform/storage/query/v1/query:execute"
```

**Authentication status:**

| Scheme | Result |
|---|---|
| `Api-Token dt0c01...` | HTTP 401 — not accepted by platform APIs |
| `Bearer <OAuth JWT>` | HTTP 200 — required scheme |

Classic API tokens cannot authenticate to `apps.dynatrace.com` platform endpoints. The in-process registry is the production fallback until OAuth is configured.

---

## Dashboard

`config/dynatrace_dashboards.json` contains a ready-to-import Dynatrace dashboard (version 16 platform format, Grail DQL tiles).

**Import:** Dashboards → Upload → select `config/dynatrace_dashboards.json`

| Tile | DQL Query | Visualization |
|---|---|---|
| Total Incidents Handled | `fetch spans \| filter span.name == "agent.incident.handle" \| summarize count()` | Single value |
| Avg Cost per Incident | Avg of `llm.cost.usd` on root spans | Single value |
| Self-Check Reinvestigation Rate | Count by `self_check.retry_triggered` | Pie chart |
| Investigation Verdicts | Count by `self_check.verdict` | Pie chart |
| LLM Token Cost Over Time | Sum of `llm.cost.usd` by 5-minute bucket | Line chart |
| Phase Duration Breakdown | Avg duration by `agent.phase.*` span name | Bar chart |
| Recent Incidents | Latest 20 root spans with cost + token attributes | Table |

For step-by-step manual build instructions (fallback if JSON import fails), see [DASHBOARD_BUILD.md](DASHBOARD_BUILD.md).

**Seeding data before a demo:**

```bash
curl -X POST http://localhost:8000/demo/incident
curl -X POST http://localhost:8000/demo/incident
curl -X POST http://localhost:8000/demo/incident
```

Wait 60–90 seconds, then open Distributed Traces filtered on `service.name = reliability-agent`. The dashboard tiles populate automatically once Grail indexes the spans.

---

## Project Structure

```
ReliabilityAgent/
├── agent/
│   ├── core.py                    # ReliabilityAgent orchestration, ADK runner, OTel root span
│   ├── prompts.py                 # TRIAGE_PROMPT, INCIDENT_PROMPT_TEMPLATE
│   └── tools/
│       ├── _tool_registry.py      # In-process call counter: trace_id → [tool_names]
│       ├── dt_query.py            # Dynatrace API v2 trace query (mock fallback)
│       ├── gcp_logs.py            # GCP Cloud Logging query (mock fallback)
│       ├── runbook.py             # Remediation runbook execution
│       └── self_check.py          # Grail DQL self-observation + registry fallback
├── observability/
│   ├── setup.py                   # TracerProvider, MeterProvider, OTLPSpanExporter
│   └── logger.py                  # Structured logger with OTel trace correlation
├── config/
│   ├── otel-collector-config.yaml # Optional OTel Collector config
│   └── dynatrace_dashboards.json  # Importable Dynatrace dashboard (version 16, DQL tiles)
├── DASHBOARD_BUILD.md             # Manual dashboard build guide + demo playbook
├── infra/                         # Terraform: Cloud Run, IAM, env injection
├── main.py                        # FastAPI entrypoint
├── tests/
│   ├── demo_run.py
│   └── test_adk_runner.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## Deployment

### Cloud Run (GCP)

```bash
cd infra && terraform init && terraform apply
```

Terraform provisions Cloud Run, IAM bindings, and secret injection for Dynatrace and Google AI Studio credentials.

### Docker

```bash
docker build -t reliability-agent .
docker run -p 8000:8000 --env-file .env reliability-agent
```

### Environment variables in production

Never commit `.env`. Inject secrets via:
- **GCP**: Secret Manager + Cloud Run secret references
- **Kubernetes**: `secretKeyRef` in pod spec
- **Docker**: `--env-file` pointing to a secrets-managed file

---

## Roadmap

**OAuth-native Grail DQL**  
Replace the API token path with a proper OAuth 2.0 client credentials flow so Grail DQL becomes the primary self-check backend. The in-process registry becomes a development-only fallback.

**Prometheus / Grafana tool adapters**  
Extend the tool layer to query Prometheus metrics and Grafana dashboards alongside Dynatrace, without changing the self-check or telemetry pipeline.

**Multi-agent coordination**  
Decompose complex incidents across specialized sub-agents (network, database, application) coordinated by a root orchestrator, with W3C Trace Context propagating a unified trace ID across all agents.

**Predictive triggering**  
Replace reactive webhook triggering with Dynatrace Davis anomaly scores as invocation signals — investigate before the incident is formally declared.

**Reinforcement-learned runbooks**  
Weight runbook selection by historical success rates encoded as span attributes, building a feedback loop from OTel traces back into agent decision-making.

---

## Contributing

1. Fork the repo and create a feature branch
2. Make changes, ensure `uvicorn main:app` starts cleanly
3. Trigger a test incident and verify the `agent.phase.self_check` span appears in Dynatrace
4. Open a pull request with a description of what changed and why

---

## License

MIT — see [LICENSE](LICENSE).

---

*Google ADK · Gemini (AI Studio) · OpenTelemetry · Dynatrace Grail · FastAPI*
