# ReliabilityAgent

### A self-observing AI reliability platform that instruments its own reasoning — and reinvestigates when its investigation falls short.

> **Dynatrace Sponsor Track — Google Cloud Rapid Agent Hackathon**  
> Built on Google Agent Development Kit · OpenRouter · OpenTelemetry · Dynatrace OTLP

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)
![Google ADK](https://img.shields.io/badge/Google%20ADK-2.1.0-4285F4?style=flat-square&logo=googlecloud)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-OTLP-blueviolet?style=flat-square)
![Dynatrace](https://img.shields.io/badge/Dynatrace-Observability-00a6c8?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi)
![OpenRouter](https://img.shields.io/badge/OpenRouter-gpt--4o--mini-orange?style=flat-square)

---

## The Problem

Modern AI agents resolve incidents faster than human engineers — but they are operationally blind.

Traditional observability ends at the infrastructure layer: CPU spikes, latency percentiles, error rates. It does not reach inside the reasoning process of the agent performing the investigation. You can see *that* an agent ran. You cannot see *what it concluded*, *why it concluded it*, *which tools it called*, or *whether it was thorough enough* to make that conclusion safely.

This creates a class of failure that infrastructure monitoring cannot surface:

- An agent queries one telemetry source, skips two others, and closes the incident with false confidence
- A hallucinated root cause passes silently through a pipeline with no enforcement gate
- A remediation executes without the minimum evidence threshold being met
- A re-investigation that should have triggered never does

**Who watches the AI agent?**

In an autonomous reliability system, the absence of self-observability is not a gap in dashboards — it is a gap in accountability.

---

## Solution

ReliabilityAgent closes this gap. It is a production-grade AI SRE agent that does not just investigate incidents — it **observes its own investigation** using Dynatrace Grail DQL and enforces correctness through a recursive self-check loop.

After remediation, the agent queries Dynatrace Grail using DQL to count how many `agent.tool` spans exist for its own trace_id, evaluates whether the investigation reached minimum depth, and — if tool coverage is insufficient — forces re-investigation before closing.

Every reasoning phase, every tool call, every verdict is exported as a structured OpenTelemetry span into Dynatrace in real time.

The result: an AI agent that is both operationally autonomous and operationally accountable.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Incident Surface                         │
│   Alert Webhook  ──►  POST /handle-incident  (FastAPI)          │
└──────────────────────────────┬──────────────────────────────────┘
                               │  BackgroundTasks (async)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Google ADK Agent Layer                      │
│                                                                 │
│   ReliabilityAgent (Runner + InMemorySessionService)            │
│         │                                                       │
│         ▼                                                       │
│   gpt-4o-mini via OpenRouter  ◄──  TRIAGE_PROMPT + INCIDENT     │
│   (LiteLlm adapter in ADK)                                      │
│         │                                                       │
│         ▼                                                       │
│   ┌─────────────────────────────────────────────────┐           │
│   │            Tool Layer (ADK FunctionTools)       │           │
│   │                                                 │           │
│   │  query_dynatrace_traces  ── Dynatrace API v2    │           │
│   │  query_gcp_logs          ── GCP Cloud Logging   │           │
│   │  execute_runbook         ── Remediation engine  │           │
│   │  verify_investigation    ── Grail DQL self-check │          │
│   │    _thoroughness           + in-process registry│           │
│   └─────────────────────────────────────────────────┘           │
│         │                                                       │
│   _tool_registry.py (in-process tool call counter)              │
│         └── keyed by OTel trace_id                              │
└──────────────────────────────┬──────────────────────────────────┘
                               │ OTLP HTTP (protobuf) — direct
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Dynatrace                               │
│                                                                 │
│   POST /api/v2/otlp/v1/traces  ← BatchSpanProcessor (5s)       │
│                                                                 │
│   Distributed Trace Waterfall  ·  Span Analysis                 │
│   Self-Check Span Attributes   ·  LLM Cost Attribution          │
│   Recursive Retry Visibility   ·  Root-Cause Traceability       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
              ┌────────────────┘ Self-Observability Loop
              │
              ▼
  verify_investigation_thoroughness
      1. Attempts Grail DQL:
         POST /platform/storage/query/v1/query:execute
         fetch spans | filter dt.trace_id == "{trace_id}"
         | filter startsWith(span.name, "agent.tool")
         | summarize tool_count = count()
      2. Falls back to in-process registry if DQL unavailable
      3. tool_count < 3  → FAILED + retry_triggered = true
         tool_count >= 3 → PASSED
```

---

## Core Capabilities

**Grail DQL self-observation**  
The agent's final step is to query Dynatrace Grail using DQL to count `agent.tool` spans for its own trace. The DQL query is the canonical source of truth. When Grail DQL is unavailable (OAuth not yet configured), the agent falls back to an in-process tool call registry — same business logic, degraded data source. No accidental recursion from backend errors.

**In-process tool registry**  
`agent/tools/_tool_registry.py` maintains a module-level dict keyed by OTel trace_id. Each tool records its call at span creation time. The registry provides a reliable local fallback for the self-check decision when Grail DQL is unreachable.

**Structured operational telemetry**  
Every phase and tool call is instrumented as a named OTel span with typed attributes. No black-box LLM calls. Spans are exported directly from the Python OTel SDK to Dynatrace via OTLP HTTP protobuf — no collector middleware required.

**Confidence-gated remediation**  
The self-check enforces `tool_count >= 3` before incident closure. Tool coverage across Dynatrace traces, GCP logs, and runbook execution is a hard requirement — not a soft recommendation.

**Token-cost attribution**  
`llm.tokens.input`, `llm.tokens.output`, `llm.cost.usd`, and `llm.model` are set as span attributes on the root `agent.incident.handle` span. Cost per resolution is queryable directly in Dynatrace without application-layer aggregation.

**Provider-agnostic LLM layer**  
ADK's `LiteLlm` adapter connects the agent to any OpenAI-compatible endpoint. Currently using `gpt-4o-mini` via OpenRouter. Switching models requires a single env-var change — no code changes.

---

## Dynatrace Integration

Dynatrace is the enforcement substrate of the self-observability loop — not a passive sink.

**Ingest path**  
The Python OTel SDK's `OTLPSpanExporter` sends protobuf traces directly to `https://{tenant}.live.dynatrace.com/api/v2/otlp/v1/traces`. `BatchSpanProcessor` exports every 5 seconds with automatic retry.

**Grail DQL self-observation**  
The self-check tool queries `POST https://{tenant}.apps.dynatrace.com/platform/storage/query/v1/query:execute`:
```dql
fetch spans
| filter dt.trace_id == "{trace_id}"
| filter startsWith(span.name, "agent.tool")
| summarize tool_count = count()
```
Result drives the pass/fail/retry decision. Requires OAuth 2.0 Bearer JWT (separate from the OTLP API token).

**Trace waterfall**  
The full agent reasoning graph appears as a distributed trace waterfall in Dynatrace. Each phase and tool call is a discrete span — duration, status, input parameters, result counts.

**Self-check span attributes**

| Attribute | Values |
|---|---|
| `self_check.dql_attempted` | `true` always |
| `self_check.dql_backend_result` | `"dynatrace_grail_dql"` or `"dql_unavailable_http_401"` |
| `self_check.query_backend` | `"dynatrace_grail_dql"` or `"in_process_registry"` |
| `self_check.tool_count` | integer |
| `self_check.verdict` | `"PASSED"`, `"FAILED"`, `"UNAVAILABLE"` |
| `self_check.retry_triggered` | `true` / `false` |
| `self_check.reason` | `"insufficient_tool_depth"` when FAILED |

**Root-cause traceability**  
`incident.id` is propagated through the entire trace. Every contributing tool call is inspectable in the waterfall without log correlation.

**Operational debugging**  
`span.record_exception()` and `span.set_status(StatusCode.ERROR)` surface failures in Dynatrace error analysis with tool inputs intact.

> Filter in Dynatrace Distributed Traces: `service.name = "reliability-agent"` or `incident.id = INC-DEMO-006`

---

## Self-Check Decision Logic

```python
# 1. Attempt Grail DQL (OAuth Bearer required)
dql_count, dql_backend = _query_dql(trace_id, dt_token)

if dql_count is not None:
    tool_count = dql_count
    query_backend = "dynatrace_grail_dql"
else:
    # 2. Fallback: in-process registry (same process, reliable)
    tool_count = get_tool_count(trace_id)   # from _tool_registry.py
    query_backend = "in_process_registry"

# 3. Business decision — only from data, never from backend errors
if tool_count == 0 and query_backend == "in_process_registry":
    return "SELF-CHECK UNAVAILABLE"   # no recursion

if tool_count < 3:
    span.set_attribute("self_check.verdict", "FAILED")
    span.set_attribute("self_check.retry_triggered", True)
    span.set_attribute("self_check.reason", "insufficient_tool_depth")
    span.add_event("self_check_failed", {...})
    return "SELF-CHECK FAILED — must re-investigate"

span.set_attribute("self_check.verdict", "PASSED")
span.add_event("self_check_passed", {...})
return "SELF-CHECK PASSED — investigation sufficient"
```

---

## Trace Hierarchy

```
agent.incident.handle  [root]
│   incident.id = INC-DEMO-006
│   incident.severity = P1
│   trace.id = <32-char hex>
│   llm.model = openrouter/openai/gpt-4o-mini
│   llm.tokens.input = <n>
│   llm.tokens.output = <n>
│   llm.cost.usd = <float>
│
├── agent.tool.dynatrace.query_traces        [registered in _tool_registry]
│       tool.name = dynatrace.query_traces
│       tool.input.query = "..."
│       tool.result.count = 12
│
├── agent.tool.gcp.query_logs               [registered in _tool_registry]
│       tool.name = gcp.query_logs
│       tool.input.filter = "..."
│       tool.result.count = 5
│
├── agent.tool.runbook.execute              [registered in _tool_registry]
│       runbook.name = "..."
│       runbook.target = "..."
│       runbook.status = success
│
├── agent.phase.self_check
│       self_check.dql_attempted = true
│       self_check.dql_backend_result = dql_unavailable_http_401
│       self_check.query_backend = in_process_registry
│       self_check.tool_count = 3
│       self_check.verdict = PASSED
│       self_check.retry_triggered = false
│       [event: self_check_passed]
│
│   [if tool_count < 3, reinvestigation spawns here]
│   ├── agent.tool.dynatrace.query_traces  [retry]
│   ├── agent.tool.gcp.query_logs          [retry]
│   └── agent.phase.self_check             [retry]
│           self_check.verdict = PASSED
│           self_check.retry_triggered = false
│
└── [incident closed]
```

---

## Incident Workflow: INC-DEMO-006

```
T+00s  POST /handle-incident received
       → span: agent.incident.handle
         incident.id = INC-DEMO-006, severity = P1
         trace_id propagated to agent prompt

T+02s  LLM (gpt-4o-mini via OpenRouter) begins reasoning
       Model selects: query_dynatrace_traces

T+15s  Tool: query_dynatrace_traces
       → span: agent.tool.dynatrace.query_traces
         Mock: "12 error traces, high latency detected"
         Registry: trace_id → ["dynatrace.query_traces"]

T+15s  Tool: query_gcp_logs
       → span: agent.tool.gcp.query_logs
         Mock: "Connection pool exhausted on db-master"
         Registry: trace_id → ["dynatrace.query_traces", "gcp.query_logs"]

T+xx s  Tool: execute_runbook
        → span: agent.tool.runbook.execute
          runbook executed, remediation confirmed
          Registry: trace_id → [..., "runbook.execute"]  (count = 3)

T+xx s  Tool: verify_investigation_thoroughness(trace_id, incident_id)
        → span: agent.phase.self_check
          1. DQL attempted → HTTP 401 (OAuth required)
          2. Fallback: registry count = 3
          3. 3 >= 3 → PASSED
          self_check.verdict = PASSED
          self_check.retry_triggered = false

T+92s  Investigation complete
       → spans flushed to Dynatrace via BatchSpanProcessor
```

---

## Project Structure

```
ReliabilityAgent/
├── agent/
│   ├── core.py                    # ReliabilityAgent class, ADK runner, OTel root span
│   ├── prompts.py                 # TRIAGE_PROMPT, INCIDENT_PROMPT_TEMPLATE
│   └── tools/
│       ├── _tool_registry.py      # In-process tool call counter (trace_id → [tool_names])
│       ├── dt_query.py            # Dynatrace API v2 trace query tool
│       ├── gcp_logs.py            # GCP Cloud Logging query tool
│       ├── runbook.py             # Remediation runbook execution tool
│       └── self_check.py          # Grail DQL self-observation + registry fallback
├── observability/
│   ├── setup.py                   # TracerProvider, MeterProvider, OTLP exporters
│   └── logger.py                  # Structured logger with OTel correlation
├── config/
│   ├── otel-collector-config.yaml # Optional OTel Collector config (not required)
│   └── dynatrace_dashboards.json  # Importable Dynatrace dashboard
├── main.py                        # FastAPI app, /handle-incident endpoint
├── tests/
│   ├── demo_run.py                # Standalone demo (limited — use FastAPI path)
│   └── test_adk_runner.py
├── requirements.txt
└── .env.example
```

---

## Quick Start

### Prerequisites

```bash
git clone https://github.com/RobertSamuel-tech/ReliabilityAgent.git
cd ReliabilityAgent
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
# OpenRouter (OpenAI-compatible — required)
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openrouter/openai/gpt-4o-mini

# Dynatrace
DYNATRACE_TENANT_URL=https://<tenant>.live.dynatrace.com
DYNATRACE_API_TOKEN=dt0c01...
OTEL_EXPORTER_OTLP_ENDPOINT=https://<tenant>.live.dynatrace.com/api/v2/otlp

# GCP (optional — falls back to mock data if not set)
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
```

### Run

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

### Trigger an incident

```bash
curl -X POST http://localhost:8000/handle-incident \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "INC-DEMO-006",
    "alert_text": "Database connection pool exhausted on api-v2. P1 incident."
  }'
```

The agent runs asynchronously (~90 seconds). Watch the server log for tool call confirmations and "Incident investigation complete".

### Observe in Dynatrace

Navigate to **Distributed Traces** and filter:
```
service.name = "reliability-agent"
```

Look for `agent.phase.self_check` to see the DQL verdict, tool count, and retry decision.

Import the command center dashboard:
```
Dynatrace → Dashboards → Import → config/dynatrace_dashboards.json
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Agent Framework | Google Agent Development Kit (ADK) 2.1.0 |
| LLM | gpt-4o-mini via OpenRouter (LiteLlm adapter) |
| API Layer | FastAPI + Uvicorn |
| Observability SDK | OpenTelemetry Python SDK |
| Telemetry Transport | OTLP HTTP protobuf (direct to Dynatrace) |
| Observability Backend | Dynatrace (OTLP ingest + Grail DQL) |
| HTTP Client | httpx |
| GCP Logging | google-cloud-logging v2 (mock fallback if auth unavailable) |

---

## Why This Matters

The deployment of autonomous AI agents into production infrastructure is accelerating. The operational frameworks for governing them are not keeping pace.

Infrastructure observability answers: *Is the system healthy?*  
Application observability answers: *Is the service behaving correctly?*

Neither answers: *Is the AI agent managing both of those things reasoning correctly?*

ReliabilityAgent is an argument — in working code — that this question is answerable. That AI agent behavior can be instrumented, exported, and analyzed with the same precision applied to distributed systems. That tool coverage, phase sequencing, and recursive self-correction are not aspirational AI safety properties — they are operational engineering properties, achievable today with OpenTelemetry and a Dynatrace backend.

The future of AI systems is not just autonomous execution. It is **observable autonomy**.

---

*Built for the Google Cloud Rapid Agent Hackathon — Dynatrace Sponsor Track.*  
*Google ADK · OpenRouter · gpt-4o-mini · OpenTelemetry · Dynatrace*
