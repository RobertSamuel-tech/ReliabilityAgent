# ReliabilityAgent

**An autonomous AI Site Reliability Engineer with full observability of its own reasoning.**

ReliabilityAgent investigates production incidents, executes remediation runbooks, and then — before closing — queries Dynatrace Grail to verify its own investigation was deep enough. If it wasn't, it reinvestigates. Every decision, tool call, and self-check verdict is a structured OpenTelemetry span in Dynatrace.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
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
Agent begins investigation
  ├── query_dynatrace_traces    → Dynatrace API v2
  ├── query_gcp_logs            → GCP Cloud Logging
  └── execute_runbook           → Remediation engine
        │
        ▼
verify_investigation_thoroughness(trace_id, incident_id)
  ├── Query Dynatrace Grail DQL:
  │     fetch spans
  │     | filter dt.trace_id == "{trace_id}"
  │     | filter startsWith(span.name, "agent.tool")
  │     | summarize tool_count = count()
  │
  ├── Fallback: in-process tool call registry (if DQL unavailable)
  │
  ├── tool_count >= 3  →  PASSED  →  close incident
  └── tool_count < 3   →  FAILED  →  re-investigate  →  repeat
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
│  LLM (gpt-4o-mini via OpenRouter, LiteLlm adapter)              │
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
│  _tool_registry.py  (trace_id → [tool_names], module-level)     │
└───────────────────────────────┬──────────────────────────────────┘
                                │ OTLP HTTP protobuf
                                │ BatchSpanProcessor (5s interval)
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Dynatrace                                                       │
│                                                                  │
│  POST /api/v2/otlp/v1/traces    ← span ingest                   │
│  POST /platform/storage/query   ← Grail DQL self-observation    │
│                                                                  │
│  Distributed Trace Waterfall · Span Attributes · Cost Metrics   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Installation

**Requirements:** Python 3.11+, a Dynatrace environment, an OpenRouter API key.

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
# ── LLM ─────────────────────────────────────────────────────────────────────
# OpenRouter provides access to 200+ models via an OpenAI-compatible API.
# Get your key at https://openrouter.ai
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openrouter/openai/gpt-4o-mini

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

The agent runs in a FastAPI `BackgroundTask`. The LLM (gpt-4o-mini) reliably invokes tools in this execution context. Direct Python invocations are non-deterministic for tool calls.

---

## Observability Contract

Every agent run produces the following OTel spans. All spans share the same `trace_id`, propagated from the root span through all child tool spans.

### Root span: `agent.incident.handle`

| Attribute | Type | Description |
|---|---|---|
| `incident.id` | string | Incident identifier |
| `incident.severity` | string | Always `"P1"` for demo |
| `trace.id` | string | 32-char hex OTel trace ID |
| `llm.model` | string | Model identifier |
| `llm.tokens.input` | int | Input token count |
| `llm.tokens.output` | int | Output token count |
| `llm.cost.usd` | float | Estimated USD cost |

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
| `self_check.dql_attempted` | bool | Always `true` |
| `self_check.dql_backend_result` | string | `"dynatrace_grail_dql"` or `"dql_unavailable_http_401"` |
| `self_check.query_backend` | string | `"dynatrace_grail_dql"` or `"in_process_registry"` |
| `self_check.tool_count` | int | Tool calls counted |
| `self_check.verdict` | string | `"PASSED"`, `"FAILED"`, `"UNAVAILABLE"` |
| `self_check.retry_triggered` | bool | `true` only when verdict is `"FAILED"` |
| `self_check.reason` | string | `"insufficient_tool_depth"` when FAILED |

Span events: `self_check_passed`, `self_check_failed`, `self_check_unavailable`.

---

## Self-Check Logic

```python
# 1. Attempt Grail DQL (requires OAuth Bearer JWT)
dql_count, backend = _query_dql(trace_id, dt_token)

if dql_count is not None:
    tool_count = dql_count
    query_backend = "dynatrace_grail_dql"
else:
    # 2. Fallback: in-process registry populated by each tool at call time
    tool_count = get_tool_count(trace_id)
    query_backend = "in_process_registry"

# 3. Business decision — data-driven only, never from backend errors
if tool_count == 0 and query_backend == "in_process_registry":
    verdict = "UNAVAILABLE"   # cannot judge, do not trigger recursion

elif tool_count < 3:
    verdict = "FAILED"
    # agent is instructed to re-investigate before closing

else:
    verdict = "PASSED"
    # incident can be closed
```

The `_tool_registry` is a module-level `defaultdict` keyed by OTel trace ID. Each tool records its call inside its own span so the key always matches the root trace ID.

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
│   └── dynatrace_dashboards.json  # Importable Dynatrace command center dashboard
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

Terraform provisions Cloud Run, IAM bindings, and secret injection for Dynatrace and OpenRouter credentials.

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

*Google ADK · OpenRouter · gpt-4o-mini · OpenTelemetry · Dynatrace Grail*
