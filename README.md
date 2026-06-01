# ReliabilityAgent

**An autonomous AI Site Reliability Engineer that observes its own reasoning in Dynatrace.**

ReliabilityAgent investigates production incidents end-to-end: it triages, queries live telemetry from Dynatrace and GCP, executes remediation runbooks, and — before closing — verifies its own investigation depth using the actual tool-call record it built during the run. Every decision, every tool invocation, and every self-check verdict is a structured OpenTelemetry span that lands in Dynatrace Grail as a searchable distributed trace.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini-2.0%20Flash-4285F4?logo=googlegemini&logoColor=white)](https://ai.google.dev)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-2.1.0-4285F4?logo=googlecloud&logoColor=white)](https://google.github.io/adk-docs/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-OTLP%20HTTP-7b52ab?logo=opentelemetry&logoColor=white)](https://opentelemetry.io)
[![Dynatrace](https://img.shields.io/badge/Dynatrace-Grail%20DQL-00a6c8)](https://www.dynatrace.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Running the Agent](#running-the-agent)
- [Demo UI](#demo-ui)
- [API Reference](#api-reference)
- [Observability Contract](#observability-contract)
- [Self-Check Logic](#self-check-logic)
- [Grail DQL Integration](#grail-dql-integration)
- [Pydantic Data Models](#pydantic-data-models)
- [Dashboard](#dashboard)
- [Deployment](#deployment)
- [Roadmap](#roadmap)

---

## Why This Exists

Most AI agents are black boxes at runtime. You can observe the infrastructure *around* them — CPU, latency, error rates — but not the reasoning *inside* them. You cannot tell whether an agent called one tool or five, whether its confidence was 0.4 or 0.9, or whether a reinvestigation should have fired but didn't.

ReliabilityAgent closes that gap by treating the agent's own reasoning as first-class telemetry:

- **Every investigation phase** is an OTel span with typed attributes
- **Every tool call** is traced, named, counted, and written to an in-process registry keyed by `trace_id`
- **After remediation**, the agent queries that registry to verify it called at least 3 distinct tools — and forces a full reinvestigation if it didn't
- **The entire recursive loop** lands in Dynatrace as one distributed trace waterfall: `investigate → self_check → reinvestigate → self_check`

This is not passive monitoring of an AI agent. It is the agent actively governing its own behavior using observability infrastructure as a feedback signal.

---

## How It Works

```
Incident arrives (webhook or /demo/incident)
        │
        ▼
┌─────────────────────────────────────────────────┐
│  agent.phase.investigate  (attempt 1)           │
│                                                 │
│  ├─ query_dynatrace_traces  → Dynatrace API v2  │
│  ├─ query_gcp_logs          → GCP Cloud Logging │
│  └─ execute_runbook         → Remediation step  │
│                                                 │
│  verify_investigation_thoroughness()            │
│    ├─ reads in-process _tool_registry           │
│    ├─ tool_count ≥ 3  →  verdict = PASSED ────► close
│    └─ tool_count < 3  →  verdict = FAILED ────►│
└─────────────────────────────────────────────────┘
        │ (self-check failed)
        ▼
┌─────────────────────────────────────────────────┐
│  agent.phase.reinvestigate  (attempt 2)         │
│                                                 │
│  Re-runs all tools with escalated context       │
│  verify_investigation_thoroughness()            │
│    └─ tool_count ≥ 3  →  verdict = PASSED ────► close
└─────────────────────────────────────────────────┘

All phases share one trace_id → single waterfall in Dynatrace
```

The agent's reinvestigation is not cosmetic. The second pass receives the explicit message "PREVIOUS INVESTIGATION FAILED SELF-CHECK — re-investigate using different tools," forcing the LLM to diversify its tool calls rather than repeat the same query.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Ingress                                                         │
│                                                                  │
│  POST /handle-incident   custom alert text                       │
│  POST /demo/incident     pre-canned P1 (no body required)        │
│  GET  /health            liveness probe                          │
│  GET  /                  static/index.html  (demo UI)            │
└───────────────────────────────┬──────────────────────────────────┘
                                │ FastAPI BackgroundTask
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Google ADK Agent Layer                                          │
│                                                                  │
│  ReliabilityAgent (agent/core.py)                                │
│    ├── Google ADK Runner + InMemorySessionService                │
│    ├── Gemini (model = GEMINI_MODEL env, default: gemini-2.0-flash)
│    ├── TRIAGE_PROMPT + INCIDENT_PROMPT_TEMPLATE                  │
│    └── max_retries = 1  (one reinvestigation per incident)       │
│                                                                  │
│  FunctionTools (all wrapped via google.adk.tools.FunctionTool)   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  query_dynatrace_traces                                  │    │
│  │    Real call: GET /api/v2/traces on DYNATRACE_TENANT_URL │    │
│  │    On failure: returns {"success": false, "error": "…"}  │    │
│  │                                                          │    │
│  │  query_gcp_logs                                          │    │
│  │    Real call: GCP Cloud Logging SDK list_log_entries     │    │
│  │    On failure: returns {"success": false, "error": "…"}  │    │
│  │                                                          │    │
│  │  execute_runbook                                         │    │
│  │    Emits OTel span; returns execution result             │    │
│  │                                                          │    │
│  │  verify_investigation_thoroughness                       │    │
│  │    Reads _tool_registry[trace_id] → real call count      │    │
│  │    Bonus: attempts Grail DQL (falls back if 401/error)   │    │
│  │    Verdict driven entirely by actual recorded calls      │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  _tool_registry.py                                               │
│    defaultdict(list): trace_id → [tool_name, tool_name, …]      │
│    Written by every tool call; read by self-check                │
└───────────────────────────────┬──────────────────────────────────┘
                                │ OTLP HTTP protobuf
                                │ BatchSpanProcessor + OTLPSpanExporter
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  OTel Collector (optional local sidecar)                         │
│    gRPC  :4317  │  HTTP  :4318                                   │
│    Processors: resourcedetection, transform/cost (llm.cost.usd)  │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Dynatrace                                                       │
│                                                                  │
│  POST /api/v2/otlp/v1/traces   ← span + metric ingest           │
│  POST /platform/storage/query  ← Grail DQL self-observation      │
│                                                                  │
│  Distributed Trace Waterfall · Span Attributes · Cost Metrics    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ReliabilityAgent/
├── agent/
│   ├── core.py                    # ReliabilityAgent class, ADK runner, retry loop, OTel root span
│   ├── prompts.py                 # TRIAGE_PROMPT, INCIDENT_PROMPT_TEMPLATE
│   ├── models/
│   │   ├── __init__.py            # Exports all Pydantic schemas
│   │   └── schemas.py             # IncidentInput, HumanFeedback, Hypothesis, AutopsyState
│   └── tools/
│       ├── _tool_registry.py      # In-process registry: trace_id → [tool_names]
│       ├── dt_query.py            # Dynatrace API v2 trace query (real call, honest errors)
│       ├── gcp_logs.py            # GCP Cloud Logging query (real call, honest errors)
│       ├── runbook.py             # Remediation runbook execution with OTel span
│       └── self_check.py          # Real tool-count self-check + Grail DQL bonus attempt
├── observability/
│   ├── setup.py                   # TracerProvider, MeterProvider, LoggerProvider, OTLPExporters
│   ├── instrumentation.py         # Custom span/metric helpers
│   └── logger.py                  # Structured logger with OTel trace correlation
├── static/
│   └── index.html                 # Self-contained dark-theme demo UI (Tailwind CDN, vanilla JS)
├── tests/
│   ├── demo_run.py                # Integration runner using the real agent
│   ├── test_adk_runner.py         # Minimal ADK smoke test
│   ├── test_collector.py          # OTel collector pipeline verification
│   ├── test_recursive_incident.py # Standalone 5-phase span waterfall emitter
│   ├── test_self_check.py         # Self-check unit tests
│   ├── test_telemetry.py          # OTel pipeline smoke test
│   └── verify_dynatrace.py        # Dynatrace API + OTLP connectivity checker
├── config/
│   ├── otel-collector-config.yaml # OTel Collector with cost transform processor
│   └── dynatrace_dashboards.json  # Importable Dynatrace dashboard (version 16, DQL tiles)
├── output/                        # Runtime logs (uvicorn, otelcol — gitignored)
├── main.py                        # FastAPI entrypoint: /handle-incident, /demo/incident, /health
├── requirements.txt
├── .env.example
└── README.md
```

---

## Quick Start

**Requirements:** Python 3.11+, a Dynatrace environment with API token, a Google AI Studio API key.

```bash
git clone https://github.com/RobertSamuel-tech/ReliabilityAgent.git
cd ReliabilityAgent

python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
cp .env.example .env               # then fill in your credentials
```

---

## Configuration

```env
# ── Google AI Studio ──────────────────────────────────────────────────────────
GOOGLE_API_KEY=AIzaSy...           # https://aistudio.google.com/app/apikey
GEMINI_MODEL=gemini-2.0-flash      # or gemini-1.5-pro, gemini-2.5-pro

# ── Dynatrace ─────────────────────────────────────────────────────────────────
DYNATRACE_TENANT_URL=https://<env-id>.live.dynatrace.com
DYNATRACE_API_TOKEN=dt0c01...      # scopes: openTelemetryTrace.ingest, logs.ingest, metrics.ingest
OTEL_EXPORTER_OTLP_ENDPOINT=https://<env-id>.live.dynatrace.com/api/v2/otlp

# ── GCP (optional) ────────────────────────────────────────────────────────────
GOOGLE_CLOUD_PROJECT=your-project  # if unset, GCP tool returns a clear auth error
GOOGLE_CLOUD_LOCATION=us-central1
```

### Dynatrace API Token Scopes

| Scope | Purpose |
|---|---|
| `openTelemetryTrace.ingest` | Receive OTLP span data |
| `logs.ingest` | Receive correlated log records |
| `metrics.ingest` | Receive `agent.tokens.total`, `agent.incident.cost_usd` |

### Grail DQL Authentication (Optional Enhancement)

The self-check tool attempts a Grail DQL query as a supplementary data point:

```
POST https://<env-id>.apps.dynatrace.com/platform/storage/query/v1/query:execute
```

This endpoint requires an **OAuth 2.0 Bearer JWT**, not a classic API token. To enable:

1. **Settings → OAuth clients → Create client** in Dynatrace
2. Grant scope: `storage:spans:read`
3. Exchange for a Bearer token and set `DYNATRACE_OAUTH_TOKEN`
4. Update `self_check.py` to use `DYNATRACE_OAUTH_TOKEN`

Without OAuth, Grail DQL returns HTTP 401. The self-check automatically uses the in-process tool-call registry instead — **investigation correctness is not affected.**

---

## Running the Agent

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Fire a real incident:

```bash
curl -X POST http://localhost:8000/handle-incident \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "INC-001",
    "alert_text": "Database connection pool exhausted on api-gateway. 95% connections active. P1."
  }'
```

Fire the pre-canned demo incident (no body required):

```bash
curl -X POST http://localhost:8000/demo/incident
```

The API response is immediate. The investigation runs asynchronously (~60–90 seconds depending on Gemini latency). Monitor server logs for real-time progress, then open Dynatrace:

```
Distributed Traces → filter: service.name = "reliability-agent"
```

---

## Demo UI

A self-contained single-page application is served at `static/index.html`. To serve it:

```bash
# Add static file serving to uvicorn (already wired in main.py if StaticFiles is mounted)
uvicorn main:app --host 0.0.0.0 --port 8000
# then open http://localhost:8000
```

**UI flow:**

| Panel | Shown when | Actions |
|---|---|---|
| **Start Form** | Page load | Enter Incident ID, Service, Time Range, Description → Start Autopsy |
| **Status & Hypothesis** | After start | Live status polling every 3s; hypothesis summary + confidence badge + evidence bullets; Approve / Redirect with feedback |
| **Postmortem Report** | After approval | Rendered markdown; Start New Autopsy button |

All three `/autopsy/*` API calls have full error handling: HTTP 4xx/5xx and network failures surface as visible error banners in the UI rather than silent failures.

---

## API Reference

### `GET /health`

Liveness probe. Returns immediately.

```json
{ "status": "healthy", "observability": "active", "agent": "ready" }
```

---

### `POST /handle-incident`

Triggers an asynchronous incident investigation.

**Request body:**

```json
{
  "incident_id": "INC-001",
  "alert_text": "Database connection pool exhausted on api-gateway. P1."
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

The agent runs inside a FastAPI `BackgroundTask` via the Google ADK `Runner`. The Gemini model reliably invokes tools in this execution context.

---

### `POST /demo/incident`

Fires a pre-canned P1 incident (`INC-DEMO-007`) — no request body. Useful for seeding Dynatrace traces before a live demo.

```bash
curl -X POST http://localhost:8000/demo/incident
```

---

## Observability Contract

Every agent run produces the following OTel span hierarchy. All spans share the same `trace_id`, propagated from the root span through all child spans.

### Span hierarchy

```
agent.incident.handle                    ← root span
  └─ agent.phase.investigate             ← attempt 1
       ├─ agent.tool.dynatrace.query_traces
       ├─ agent.tool.gcp.query_logs
       ├─ agent.tool.runbook.execute
       └─ agent.phase.self_check         ← verdict: FAILED
  └─ agent.phase.reinvestigate           ← attempt 2 (if self-check failed)
       ├─ agent.tool.dynatrace.query_traces
       ├─ agent.tool.gcp.query_logs
       ├─ agent.tool.runbook.execute
       └─ agent.phase.self_check         ← verdict: PASSED
```

### Root span: `agent.incident.handle`

| Attribute | Type | Description |
|---|---|---|
| `incident.id` | string | Incident identifier |
| `incident.severity` | string | `"P1"` |
| `trace.id` | string | 32-char hex OTel trace ID |
| `incident.attempts` | int | Investigation attempts (1 = passed first time) |
| `incident.status` | string | `"resolved"` or `"escalated"` |
| `llm.model` | string | Gemini model name |
| `llm.tokens.input` | int | Total input tokens |
| `llm.tokens.output` | int | Total output tokens |
| `llm.cost.usd` | float | USD cost (tokens × Gemini pricing table) |

### Tool spans

| Span name | Tool | Key attributes |
|---|---|---|
| `agent.tool.dynatrace.query_traces` | Dynatrace API v2 | `tool.status_code`, `tool.result.count` |
| `agent.tool.gcp.query_logs` | GCP Cloud Logging SDK | `tool.result.count`, `tool.error` |
| `agent.tool.runbook.execute` | Remediation engine | `runbook.name`, `runbook.target`, `runbook.status` |

On API failure, tools return `{"success": false, "error": "<actual error>", "data": []}` — no fake data is ever returned.

### Self-check span: `agent.phase.self_check`

| Attribute | Type | Values |
|---|---|---|
| `self_check.trace_id` | string | Trace being evaluated |
| `self_check.incident_id` | string | Incident being verified |
| `self_check.tool_count` | int | Actual recorded tool calls from registry |
| `self_check.backend` | string | `"in_process_registry"` (primary) or `"dynatrace_grail_dql"` (bonus) |
| `self_check.verdict` | string | `"PASSED"` or `"FAILED"` |
| `self_check.retry_triggered` | bool | `true` when verdict is `"FAILED"` |
| `self_check.dql_attempted` | bool | Always `true` |
| `self_check.dql_backend_result` | string | DQL HTTP status or error class |

Span events: `self_check_passed`, `self_check_failed`.

---

## Self-Check Logic

The self-check is real. There is no mock, no modulo arithmetic, no deterministic counter. The verdict is driven entirely by the actual number of tool calls recorded during the investigation.

### In-process registry (`agent/tools/_tool_registry.py`)

Every tool writes to a module-level `defaultdict(list)` keyed by `trace_id` when it executes:

```python
# _tool_registry.py
_registry: dict[str, list[str]] = defaultdict(list)

def record_tool_call(trace_id: str, tool_name: str) -> None:
    if trace_id: _registry[trace_id].append(tool_name)

def get_tool_count(trace_id: str) -> int:
    return len(_registry.get(trace_id, []))
```

### Self-check verdict (`agent/tools/self_check.py`)

```python
_MIN_TOOL_CALLS = 3

def verify_investigation_thoroughness(trace_id: str, incident_id: str) -> dict:
    tool_count = get_tool_count(trace_id)   # reads real recorded calls
    verdict = "PASSED" if tool_count >= _MIN_TOOL_CALLS else "FAILED"
    return {"verdict": verdict, "tool_count": tool_count, "backend": "in_process_registry"}
```

Grail DQL is attempted as a supplementary data point (logged as span attributes for Dynatrace visibility), but **does not override the registry verdict**. If DQL returns 401 (OAuth not configured), the registry count is used and investigation correctness is unaffected.

### Python retry loop (`agent/core.py`)

```python
while attempts <= max_retries and not self_check_passed:
    attempts += 1
    phase_name = "agent.phase.investigate" if attempts == 1 \
                 else "agent.phase.reinvestigate"

    with tracer.start_as_current_span(phase_name) as phase_span:
        # Run ADK agent → Gemini calls tools → calls verify_investigation_thoroughness
        ...
        result_text = str(result).lower()
        self_check_passed = "self-check passed" in result_text or \
                            "sufficient" in result_text
```

---

## Grail DQL Integration

When OAuth is configured, the self-check queries Grail with:

```sql
fetch spans
| filter dt.trace_id == "<trace_id>"
| filter startsWith(span.name, "agent.tool")
| summarize tool_count = count()
```

The `apps.dynatrace.com` endpoint is derived at runtime from `DYNATRACE_TENANT_URL`:

```python
apps_host = tenant.replace(".live.dynatrace.com", ".apps.dynatrace.com")
endpoint = f"{apps_host}/platform/storage/query/v1/query:execute"
```

**Auth behavior:**

| Token type | Result |
|---|---|
| `Api-Token dt0c01…` | HTTP 401 — classic tokens not accepted by platform APIs |
| `Bearer <OAuth JWT>` | HTTP 200 — required for Grail DQL |

Until OAuth is configured, the DQL attempt is a no-op: it records the HTTP status as a span attribute and returns gracefully. The in-process registry is the production-grade fallback.

---

## Pydantic Data Models

`agent/models/schemas.py` defines the data contracts for the Autopsy API. Pure Pydantic — no database, no ORM.

```python
class IncidentInput(BaseModel):
    incident_id: str
    service_name: str
    time_range: str = "-1h"
    description: Optional[str] = None

class HumanFeedback(BaseModel):
    action: Literal["approve", "redirect"]
    feedback: str
    additional_context: Optional[str] = None

class Hypothesis(BaseModel):
    summary: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    evidence: List[str] = []
    full_analysis: str = ""

class AutopsyState(BaseModel):
    incident_id: str
    service_name: str
    time_range: str
    description: Optional[str] = None
    status: Literal["collecting", "awaiting_review", "approved",
                    "redirected", "completed", "failed"] = "collecting"
    hypothesis: Optional[Hypothesis] = None
    evidence: Dict[str, Any] = {}
    human_feedback: Optional[HumanFeedback] = None
    postmortem: Optional[str] = None
    error: Optional[str] = None
```

---

## Dashboard

`config/dynatrace_dashboards.json` is a ready-to-import Dynatrace dashboard (version 16 platform format, Grail DQL tiles).

**Import:** Dashboards → Upload → select `config/dynatrace_dashboards.json`

| Tile | What it shows |
|---|---|
| Total Incidents Handled | Count of `agent.incident.handle` root spans |
| Avg Cost per Incident | Mean `llm.cost.usd` on root spans |
| Self-Check Reinvestigation Rate | `self_check.retry_triggered` true vs. false |
| Investigation Verdicts | `self_check.verdict` distribution |
| LLM Token Cost Over Time | `llm.cost.usd` sum by 5-minute bucket |
| Phase Duration Breakdown | Mean duration by `agent.phase.*` span name |
| Recent Incidents | Latest 20 root spans with cost, token, and status attributes |

**Seed data before a demo:**

```bash
# Fire three incidents so the dashboard tiles have data
curl -X POST http://localhost:8000/demo/incident
curl -X POST http://localhost:8000/demo/incident
curl -X POST http://localhost:8000/demo/incident
```

Wait ~90 seconds, then open Distributed Traces filtered on `service.name = reliability-agent`. Dashboard tiles populate automatically once Grail indexes the spans.

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

### Secrets in production

Never commit `.env`. Inject credentials via:

| Platform | Method |
|---|---|
| GCP Cloud Run | Secret Manager + `--set-secrets` flag |
| Kubernetes | `secretKeyRef` in pod spec |
| Docker | `--env-file` pointing to a secrets-managed file |

---

## Roadmap

**OAuth-native Grail DQL**
Replace the API token path with a proper OAuth 2.0 client credentials flow so Grail DQL becomes the primary self-check backend. The in-process registry remains a development-only fallback.

**Human-in-the-loop Autopsy API**
Wire the Pydantic `AutopsyState` / `HumanFeedback` models into a stateful `/autopsy/*` endpoint set so operators can approve or redirect investigations through the demo UI before a postmortem is written.

**Prometheus / Grafana tool adapters**
Extend the tool layer to query Prometheus metrics and Grafana dashboards alongside Dynatrace, without changing the self-check or telemetry pipeline.

**Multi-agent coordination**
Decompose complex incidents across specialised sub-agents (network, database, application) coordinated by a root orchestrator, with W3C Trace Context propagating a unified `trace_id` across all agents.

**Predictive triggering**
Replace reactive webhook triggering with Dynatrace Davis anomaly scores as invocation signals — investigate before the incident is formally declared.

**Reinforcement-learned runbooks**
Weight runbook selection by historical success rates stored as span attributes, building a feedback loop from OTel traces back into agent decision-making.

---

## Contributing

1. Fork and create a feature branch
2. Ensure `uvicorn main:app` starts cleanly and imports pass: `python -c "from main import app"`
3. Trigger a test incident and verify `agent.phase.self_check` appears in Dynatrace Distributed Traces
4. Open a pull request describing what changed and why — link the Dynatrace trace screenshot if relevant

---

## License

MIT — see [LICENSE](LICENSE).

---

*Google ADK · Gemini (AI Studio) · OpenTelemetry · Dynatrace Grail · FastAPI · Pydantic*
