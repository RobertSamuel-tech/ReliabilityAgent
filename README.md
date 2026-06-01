# ReliabilityAgent

**An autonomous AI SRE that observes its own reasoning inside Dynatrace.**

Gemini investigates production incidents — queries live telemetry, executes runbooks, synthesizes root cause — then verifies its own thoroughness by reading the tool-call record it built during the run. Every phase, tool call, and self-check verdict is an OTel span in Dynatrace Grail. If the self-check fails, the agent reinvestigates. All of it lands as a single trace waterfall.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini-2.0%20Flash-4285F4?logo=googlegemini&logoColor=white)](https://ai.google.dev)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-2.1.0-4285F4?logo=googlecloud&logoColor=white)](https://google.github.io/adk-docs/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-OTLP%20HTTP-7b52ab?logo=opentelemetry&logoColor=white)](https://opentelemetry.io)
[![Dynatrace](https://img.shields.io/badge/Dynatrace-Grail%20DQL-00a6c8)](https://www.dynatrace.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)

---

## Killer Features

| # | Feature | Why It Matters |
|---|---|---|
| 1 | **Recursive self-observability loop** | After investigation, the agent queries its own Dynatrace trace to verify it called ≥ 3 distinct tools. Insufficient coverage triggers a full reinvestigation — automatically. |
| 2 | **Dynatrace as a cognitive feedback signal** | The agent doesn't just *emit* telemetry to Dynatrace — it *reads back from it* to govern its own next action. Observability becomes part of the control plane. |
| 3 | **Zero mock data, zero fake verdicts** | Every tool returns real API responses or honest error structs. `self_check.verdict` is driven by actual recorded tool calls in an in-process registry — not a counter, flag, or modulo. |
| 4 | **Human-in-the-loop autopsy API** | `/autopsy/start` → Gemini gathers evidence → structured hypothesis with confidence score → operator approves or redirects → Gemini writes the postmortem. Every step is an auditable state machine. |
| 5 | **Full OTel span hierarchy, importable dashboard** | 7 span types, 20+ typed attributes, cost accounting (`llm.cost.usd`), phase durations, verdict distribution — all queryable via Grail DQL. Dashboard ships as an importable JSON. |
| 6 | **Production-grade observability stack** | `TracerProvider` + `MeterProvider` + `LoggerProvider` all wired to Dynatrace via OTLP HTTP. Structured logs carry `trace_id` correlation. Token cost computed per-model and recorded as a span attribute and OTel metric. |
| 7 | **Docker + Cloud Run ready** | `Dockerfile` and `deploy/gcloud/deploy.sh` included. One command deploys to GCP Cloud Run with correct memory, CPU, and timeout settings. |

---

## What Makes This Different

Most AI agents are black boxes at runtime. ReliabilityAgent treats agent reasoning as first-class telemetry:

- **Recursive self-observability**: after investigation, the agent reads its own Dynatrace trace to verify it called ≥ 3 distinct tools — and forces a full reinvestigation if it didn't
- **Real verdicts, zero mocks**: `self_check.verdict` is driven by actual recorded tool calls, not a counter or modulo
- **Dynatrace as a feedback signal**: the agent doesn't just *send* telemetry to Dynatrace — it *reads from it* to govern its own behavior
- **Human oversight built in**: the `/autopsy/*` API delivers structured hypothesis → human review → Gemini-generated postmortem

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  INGRESS  (FastAPI — main.py)                                       │
│                                                                     │
│  POST /handle-incident   custom alert webhook                       │
│  POST /demo/incident     pre-canned P1 — no body required           │
│  POST /autopsy/start     stateful RCA with human review             │
│  GET  /autopsy/{id}/status                                          │
│  POST /autopsy/{id}/feedback   approve | redirect                   │
│  GET  /ui                dark-theme SPA (static/index.html)         │
│  GET  /health            liveness probe                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │ FastAPI BackgroundTask (non-blocking)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AGENT LAYER  (agent/core.py)                                       │
│                                                                     │
│  ReliabilityAgent                                                   │
│    ├── Google ADK Runner + InMemorySessionService                   │
│    ├── Gemini (gemini-2.0-flash, configurable via GEMINI_MODEL)     │
│    ├── TRIAGE_PROMPT + INCIDENT_PROMPT_TEMPLATE                     │
│    └── Retry loop: max_retries = 1 (one reinvestigation per run)    │
│                                                                     │
│  TOOLS  (all wrapped as google.adk.tools.FunctionTool)              │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │ query_dynatrace_traces                                     │     │
│  │   GET /api/v2/traces on DYNATRACE_TENANT_URL               │     │
│  │   Failure → {"success": false, "error": "<real msg>"}      │     │
│  │                                                            │     │
│  │ query_gcp_logs                                             │     │
│  │   GCP Cloud Logging SDK  list_log_entries                  │     │
│  │   Failure → {"success": false, "error": "<real msg>"}      │     │
│  │                                                            │     │
│  │ execute_runbook                                            │     │
│  │   Emits agent.tool.runbook.execute OTel span               │     │
│  │   Records tool call in registry                            │     │
│  │                                                            │     │
│  │ verify_investigation_thoroughness                          │     │
│  │   Reads _tool_registry[trace_id] → real call count         │     │
│  │   verdict = PASSED if count ≥ 3 else FAILED                │     │
│  │   Bonus: attempts Grail DQL (graceful 401 fallback)        │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                     │
│  _tool_registry.py                                                  │
│    defaultdict(list): trace_id → [tool_name, ...]                   │
│    Written on every tool call · Read by self-check                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │ OTLP HTTP (protobuf)
                             │ BatchSpanProcessor · OTLPSpanExporter
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OBSERVABILITY  (observability/)                                    │
│                                                                     │
│  TracerProvider  → OTLPSpanExporter   → /api/v2/otlp/v1/traces     │
│  MeterProvider   → OTLPMetricExporter → /api/v2/otlp/v1/metrics    │
│  LoggerProvider  → OTLPLogExporter    → /api/v2/otlp/v1/logs       │
│                                                                     │
│  Metrics emitted:                                                   │
│    agent.tokens.total      (counter, labelled by model)             │
│    agent.incident.cost_usd (histogram, labelled by incident.id)     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DYNATRACE GRAIL                                                    │
│                                                                     │
│  Distributed Trace Waterfall  ← agent.incident.handle root span     │
│  Span Attribute Search        ← self_check.verdict, llm.cost.usd    │
│  DQL Dashboard (7 tiles)      ← config/dynatrace_dashboards.json    │
│  Grail DQL self-check         ← agent reads its own spans           │
└─────────────────────────────────────────────────────────────────────┘
```

**Span waterfall — every incident produces this hierarchy:**

```
agent.incident.handle                      ← root (cost, tokens, status)
  └─ agent.phase.investigate               ← attempt 1
       ├─ agent.tool.dynatrace.query_traces
       ├─ agent.tool.gcp.query_logs
       ├─ agent.tool.runbook.execute
       └─ agent.phase.self_check           ← verdict: FAILED → retry
  └─ agent.phase.reinvestigate             ← attempt 2
       ├─ agent.tool.dynatrace.query_traces
       ├─ agent.tool.gcp.query_logs
       ├─ agent.tool.runbook.execute
       └─ agent.phase.self_check           ← verdict: PASSED → close
```

---

## Project Structure

```
ReliabilityAgent/
├── agent/
│   ├── core.py                    # ReliabilityAgent, ADK runner, retry loop, root OTel span
│   ├── prompts.py                 # TRIAGE_PROMPT, INCIDENT_PROMPT_TEMPLATE
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py             # IncidentInput, HumanFeedback, Hypothesis, AutopsyState
│   └── tools/
│       ├── _tool_registry.py      # defaultdict(list): trace_id → [tool_names]
│       ├── dt_query.py            # Dynatrace API v2 — real call, honest errors
│       ├── gcp_logs.py            # GCP Cloud Logging SDK — real call, honest errors
│       ├── runbook.py             # Runbook execution with OTel span
│       └── self_check.py          # Registry-based verdict + Grail DQL bonus attempt
├── observability/
│   ├── setup.py                   # TracerProvider, MeterProvider, LoggerProvider, exporters
│   ├── instrumentation.py         # Custom span/metric helpers
│   └── logger.py                  # Structured logger with trace_id correlation
├── static/
│   └── index.html                 # Dark-theme SPA: Start → Hypothesis → Postmortem
├── tests/
│   ├── test_integration.py        # 7 integration tests (imports, routes, schemas, self-check)
│   ├── test_self_check.py
│   ├── test_adk_runner.py
│   ├── test_recursive_incident.py
│   ├── test_collector.py
│   ├── test_telemetry.py
│   ├── demo_run.py
│   └── verify_dynatrace.py
├── config/
│   ├── otel-collector-config.yaml # OTel Collector with cost transform processor
│   └── dynatrace_dashboards.json  # Importable dashboard — version 16, 7 DQL tiles
├── deploy/
│   └── gcloud/
│       └── deploy.sh              # Cloud Run deploy (chmod +x, one command)
├── Dockerfile                     # python:3.11-slim, OTLP env vars, port 8080
├── main.py                        # FastAPI: all endpoints, autopsy state machine
├── requirements.txt
├── .env.example
└── README.md
```

---

## Quick Start

```bash
git clone https://github.com/RobertSamuel-tech/ReliabilityAgent.git
cd ReliabilityAgent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in GOOGLE_API_KEY + Dynatrace creds
uvicorn main:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST http://localhost:8000/demo/incident
# Dynatrace → Distributed Traces → filter service.name = "reliability-agent"
```

Open the UI: **http://localhost:8000/ui**

---

## Demo UI

`GET /ui` serves a dark-theme SPA (`static/index.html`) with three panels:

| Panel | Trigger | Actions |
|---|---|---|
| **Start Form** | Page load | Incident ID, service, time range, description → Start Autopsy |
| **Status & Hypothesis** | After start, polling every 3 s | Confidence badge, evidence bullets → Approve or Redirect |
| **Postmortem Report** | After approval | Gemini-generated markdown postmortem |

---

## Observability Contract

**`agent.incident.handle`** (root): `incident.id`, `incident.severity`, `llm.model`, `llm.tokens.input`, `llm.tokens.output`, `llm.cost.usd`, `incident.attempts`, `incident.status`

**`agent.phase.self_check`**: `self_check.verdict` (`PASSED`/`FAILED`), `self_check.tool_count`, `self_check.retry_triggered`, `self_check.backend`

---

## Self-Check Logic

Every tool writes to an in-process registry keyed by `trace_id`. The self-check reads that registry — not a counter, not a mock:

```python
# _tool_registry.py
_registry: dict[str, list[str]] = defaultdict(list)
def record_tool_call(trace_id, tool_name): _registry[trace_id].append(tool_name)

# self_check.py
_MIN_TOOL_CALLS = 3
tool_count = get_tool_count(trace_id)          # reads actual recorded calls
verdict = "PASSED" if tool_count >= _MIN_TOOL_CALLS else "FAILED"
```

On `FAILED`, `agent/core.py` emits `agent.phase.reinvestigate` and injects: *"PREVIOUS INVESTIGATION FAILED SELF-CHECK — re-investigate using different tools."*

---

## Dashboard

Import `config/dynatrace_dashboards.json` (Dashboards → Upload). Seed data:

```bash
curl -X POST http://localhost:8000/demo/incident   # run 2–3 times
```

| Tile | DQL source |
|---|---|
| Total Incidents Handled | `agent.incident.handle` span count |
| Self-Check Reinvestigation Rate | `self_check.retry_triggered` |
| Investigation Verdicts | `self_check.verdict` distribution |
| LLM Token Cost Over Time | `llm.cost.usd` sum by 5 min |
| Phase Duration Breakdown | avg `duration` by `agent.phase.*` |
| Recent Incidents | latest 20 root spans with cost + tokens |
