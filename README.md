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

## What Makes This Different

Most AI agents are black boxes at runtime. ReliabilityAgent treats agent reasoning as first-class telemetry:

- **Recursive self-observability**: after investigation, the agent reads its own Dynatrace trace to verify it called ≥ 3 distinct tools — and forces a full reinvestigation if it didn't
- **Real verdicts, zero mocks**: `self_check.verdict` is driven by actual recorded tool calls, not a counter or modulo
- **Dynatrace as a feedback signal**: the agent doesn't just *send* telemetry to Dynatrace — it *reads from it* to govern its own behavior
- **Human oversight built in**: the `/autopsy/*` API delivers structured hypothesis → human review → Gemini-generated postmortem

---

## How It Works

```
Incident → investigate → [query_dt, query_gcp, runbook, self_check → FAILED]
                ↓
           reinvestigate → [tools re-run with escalated context, self_check → PASSED] → close

All phases share one trace_id → single waterfall in Dynatrace Distributed Traces
```

---

## Architecture

```
POST /handle-incident ─► FastAPI BackgroundTask
POST /demo/incident        │
GET  /ui  (demo SPA)       ▼
                  ReliabilityAgent (Google ADK + Gemini)
                    ├─ query_dynatrace_traces  (real API)
                    ├─ query_gcp_logs          (real SDK)
                    ├─ execute_runbook         (OTel span)
                    └─ verify_investigation_thoroughness
                            │ reads _tool_registry[trace_id]
                            ▼
                  OTel SDK ─OTLP HTTP─► Dynatrace Grail
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

## Demo Video & Screenshots

> _Demo video link · Dynatrace trace waterfall · Dashboard tiles · Demo UI panels_

---

## Observability Contract

```
agent.incident.handle                    ← root span
  └─ agent.phase.investigate / reinvestigate
       ├─ agent.tool.dynatrace.query_traces
       ├─ agent.tool.gcp.query_logs
       ├─ agent.tool.runbook.execute
       └─ agent.phase.self_check
```

**`agent.incident.handle`**: `incident.id`, `incident.severity`, `llm.model`, `llm.tokens.input`, `llm.tokens.output`, `llm.cost.usd`, `incident.attempts`, `incident.status`

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

The retry loop in `agent/core.py` emits `agent.phase.reinvestigate` on the second pass and passes an escalated prompt: *"PREVIOUS INVESTIGATION FAILED SELF-CHECK — re-investigate using different tools."*

---

## Dashboard

Import `config/dynatrace_dashboards.json` into Dynatrace (Dashboards → Upload). Seed data first:

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
