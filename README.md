# ReliabilityAgent

### A self-observing AI reliability platform that instruments its own reasoning — and reinvestigates when its confidence falls short.

> **Dynatrace Sponsor Track — Google Cloud Rapid Agent Hackathon**
> Built on Google Agent Development Kit · Vertex AI Agent Platform · Gemini 2.5 Pro · OpenTelemetry · Dynatrace OTLP

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-OTLP-blueviolet?style=flat-square)
![Dynatrace](https://img.shields.io/badge/Dynatrace-Observability-00a6c8?style=flat-square)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Pro-orange?style=flat-square&logo=google)
![Vertex AI](https://img.shields.io/badge/Vertex%20AI-Agent%20Platform-4285F4?style=flat-square&logo=googlecloud)

---

## The Problem

Modern AI agents resolve incidents faster than human engineers — but they are operationally blind.

Traditional observability ends at the infrastructure layer: CPU spikes, latency percentiles, error rates. It does not reach inside the reasoning process of the agent performing the investigation. You can see *that* an agent ran. You cannot see *what* it concluded, *why* it concluded it, *which tools it called*, or *whether it was thorough enough* to make that conclusion safely.

This creates a class of failure that infrastructure monitoring cannot surface:

- An agent queries one telemetry source, skips two others, and closes the incident with false confidence
- A hallucinated root cause passes silently through a pipeline with no enforcement gate
- A remediation executes without the minimum evidence threshold being met
- A re-investigation that should have triggered never does

**Who watches the AI agent?**

In an autonomous reliability system, the absence of self-observability is not a gap in dashboards — it is a gap in accountability.

---

## Solution

ReliabilityAgent closes this gap. It is a production-grade AI SRE agent that does not just investigate incidents — it **observes its own investigation** and enforces correctness through a recursive self-check loop.

Every reasoning phase, every tool call, every confidence score is exported as a structured OpenTelemetry span into Dynatrace. After remediation, the agent queries Dynatrace for its *own* distributed trace, scores the investigation against a defined sufficiency rubric, and — if the score falls below threshold — forces re-investigation before closing.

The result: an AI agent that is both operationally autonomous and operationally accountable.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Incident Surface                         │
│   Alert Webhook  ──►  POST /handle-incident  (FastAPI)          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Google ADK Agent Layer                      │
│                                                                 │
│   ReliabilityAgent (Runner + InMemorySessionService)            │
│         │                                                       │
│         ▼                                                       │
│   Gemini 2.5 Pro  ◄──  TRIAGE_PROMPT + INCIDENT_PROMPT          │
│         │                                                       │
│         ▼                                                       │
│   ┌─────────────────────────────────────────────────┐           │
│   │               Tool Layer (ADK FunctionTools)    │           │
│   │                                                 │           │
│   │  query_dynatrace_traces  ─── Dynatrace API v2   │           │
│   │  query_gcp_logs          ─── GCP Logging v2     │           │
│   │  execute_runbook         ─── Remediation engine │           │
│   │  verify_investigation    ─── Self-check loop    │           │
│   │    _thoroughness           (queries own trace)  │           │
│   └─────────────────────────────────────────────────┘           │
└──────────────────────────────┬──────────────────────────────────┘
                               │ OTLP HTTP
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OpenTelemetry Collector                      │
│                                                                 │
│   receivers:   otlp (gRPC :4317, HTTP :4318)                    │
│   processors:  resourcedetection/gcp → transform/cost → batch   │
│   exporters:   otlphttp/dynatrace  +  debug  +  file            │
└──────────────────────────────┬──────────────────────────────────┘
                               │ OTLP → Dynatrace Ingest API
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Dynatrace                               │
│                                                                 │
│   Distributed Trace Waterfall  ·  Span Analysis                 │
│   Self-Check Span Visibility   ·  LLM Cost Attribution          │
│   Recursive Retry Visibility   ·  Root-Cause Traceability       │
└─────────────────────────────────────────────────────────────────┘
                               │
                    ┌──────────┘ (Self-Observability Loop)
                    │
                    ▼
        verify_investigation_thoroughness
            queries Dynatrace API v2
            for agent's OWN trace_id
            scores 6 rubric checks
            score < 0.7 → reinvestigate
            score ≥ 0.7 → close incident
```

---

## Core Capabilities

**Recursive self-observability**
The agent's final investigation step is to fetch its own distributed trace from Dynatrace and score it. If the score falls below the sufficiency threshold, the agent is forced back into investigation mode. This loop is itself a traceable span.

**Structured operational telemetry**
Every phase of reasoning (`triage`, `diagnose`, `self_check`, `reinvestigate`, `final_decision`) and every tool call is instrumented as a named OTel span with typed attributes. No black-box LLM calls.

**Confidence-gated remediation**
Span attribute `diagnosis.confidence` (0.0–1.0) is set during diagnosis. The self-check enforces that confidence reaches threshold before incident closure is permitted.

**Token-cost attribution**
Custom metrics `agent.tokens.total` and `agent.incident.cost_usd` are exported per incident, enabling cost-per-resolution analysis at the infrastructure layer.

**Tool-call coverage enforcement**
The self-check rubric requires a minimum of three distinct tool calls covering Dynatrace traces, GCP logs, and metrics. Partial investigations fail automatically.

**Production-grade OTLP pipeline**
BatchSpanProcessor with retry queue, sending queue depth control, and fallback to local file export. Collector-side cost transformation via OTel processor DSL.

---

## Dynatrace Integration

Dynatrace is not a passive sink for this agent's telemetry — it is the enforcement substrate of the self-observability loop.

**Ingest path**
Spans and metrics are exported via OTLP HTTP to the Dynatrace ingest API (`/api/v2/otlp`). The OTel Collector handles batching, retry, and queue management before forwarding.

**Trace waterfall**
The full agent reasoning graph appears as a distributed trace waterfall in Dynatrace Distributed Traces. Each phase and tool call is a discrete span with typed attributes — duration, status, input parameters, result counts, confidence scores.

**Self-check loop visibility**
`agent.phase.self_check` spans expose the 6-check rubric result (`self_check.score`, `self_check.verdict`, `self_check.tool_calls`, `self_check.phases`) directly in the trace. When reinvestigation triggers, the resulting spans attach as children within the same trace, making the recursive retry sequence fully visible in the waterfall.

**Root-cause traceability**
Span attribute `incident.id` is propagated through the entire trace, enabling trace search by incident identifier. Every tool call that contributed to the final diagnosis is inspectable without log correlation.

**Operational debugging**
When an agent call fails — auth error, API timeout, malformed response — `span.record_exception()` and `span.set_status(StatusCode.ERROR)` surface the failure in Dynatrace's error analysis view, with the span's tool inputs intact for debugging.

**Cost attribution**
The collector's `transform/cost` processor computes `llm.cost.usd` from token counts inline: `(input_tokens × $0.00000125) + (output_tokens × $0.000005)`. Cost per incident is queryable as a Dynatrace metric without any application-layer aggregation.

> Without Dynatrace, the agent is blind to its own behavior. Tool call coverage, confidence trajectories, retry chains, and cost profiles exist only as instrumented spans. Dynatrace makes them observable, searchable, and alertable.

---

## OpenTelemetry Pipeline

```yaml
# config/otel-collector-config.yaml

receivers:
  otlp:
    protocols:
      http: { endpoint: localhost:4318 }
      grpc: { endpoint: localhost:4317 }

processors:
  resourcedetection/gcp:           # auto-attach GCP resource attributes
    detectors: [gcp, env]
  transform/cost:                  # compute LLM cost from token attributes
    trace_statements:
      - set(attributes["llm.cost.usd"],
            (attributes["llm.tokens.input"] * 0.00000125) +
            (attributes["llm.tokens.output"] * 0.000005))
        where attributes["llm.tokens.input"] != nil
  batch:
    send_batch_size: 1024
    timeout: 5s

exporters:
  otlphttp/dynatrace:
    endpoint: https://<tenant>.live.dynatrace.com/api/v2/otlp
    headers: { Authorization: "Api-Token ${DYNATRACE_API_TOKEN}" }
    sending_queue: { enabled: true, num_consumers: 4, queue_size: 100 }
    retry_on_failure: { enabled: true, max_elapsed_time: 300s }
  debug: { verbosity: detailed }
  file: { path: ./output/traces.json }
```

The pipeline follows OTel semantic conventions throughout: `service.name`, `service.version`, `deployment.environment`, `gcp.project.id`. Span names use dot-notation namespacing (`agent.tool.gcp.query_logs`) to enable hierarchical filtering in Dynatrace.

---

## Incident Workflow: INC-404 Payment Gateway Outage

```
T+00s  Webhook received: "CPU spike on payment-gateway. 95% connections active. Latency >2s."
       → span: agent.incident.handle
         attributes: incident.id=INC-404, incident.severity=P1

T+01s  Triage phase initiated
       → span: agent.phase.triage
         Gemini classifies: service_degradation, P1, payment-gateway

T+03s  Diagnosis phase: query Dynatrace traces
       → span: agent.tool.dynatrace.query_traces
         filter: service=payment-gateway, time=now-1h
         result: 847 error traces, p99 latency=4.2s, connection_pool_exhausted

T+06s  Diagnosis phase: query GCP logs
       → span: agent.tool.gcp.query_logs
         filter: severity>=ERROR, resource=payment-gateway
         result: "Connection pool exhausted on db-master", 95/100 connections active

T+09s  Diagnosis phase: query metrics
       → span: agent.tool.dynatrace.query_traces (metrics variant)
         result: db connection saturation confirmed, auto-scaling not triggered

T+11s  Gemini sets diagnosis.confidence=0.91
       Root cause: database connection pool exhausted due to query timeout cascade

T+12s  Remediation executed
       → span: agent.tool.execute_runbook
         action: flush_connection_pool + scale_db_connections
         runbook: DB-CONNPOOL-001

T+14s  Self-check initiated — agent queries its own trace
       → span: agent.phase.self_check
         self_check.trace_id: <propagated_trace_id>
         Calls Dynatrace API v2: GET /api/v2/traces/{trace_id}

T+16s  Rubric evaluation:
         ✓ min_3_tools: 4 tool calls found
         ✓ queried_traces: dynatrace.query_traces present
         ✓ queried_logs: gcp.query_logs present
         ✓ queried_metrics: metrics query present
         ✓ all_phases: 5 phases present
         ✓ high_confidence: diagnosis.confidence=0.91 ≥ 0.80
         score: 6/6 = 1.0

T+17s  self_check.verdict: SUFFICIENT
       → span: agent.phase.final_decision
         Incident INC-404 closed. Trace exported to Dynatrace.

Total duration: ~17s end-to-end, fully traceable.
```

*When self-check fails (score < 0.7): `agent.phase.reinvestigate` spawns as a child span of the same root trace, with retry tool calls attached beneath it. The entire recursive sequence is visible as a single waterfall in Dynatrace.*

---

## Trace Hierarchy

```
agent.incident.handle  [root]
│   incident.id = INC-404
│   incident.severity = P1
│   trace.id = <32-char hex>
│
├── agent.phase.triage
│       classification = service_degradation
│       severity = P1
│
├── agent.phase.diagnose
│   │   diagnosis.confidence = 0.91
│   │
│   ├── agent.tool.dynatrace.query_traces
│   │       tool.input.query = "payment-gateway errors"
│   │       tool.result.count = 847
│   │       tool.status_code = 200
│   │
│   ├── agent.tool.gcp.query_logs
│   │       tool.input.filter = "severity>=ERROR"
│   │       tool.result.count = 5
│   │       tool.mock_data = false
│   │
│   └── agent.tool.execute_runbook
│           runbook.id = DB-CONNPOOL-001
│           runbook.action = flush_connection_pool
│
├── agent.phase.self_check
│       self_check.score = 1.0
│       self_check.verdict = SUFFICIENT
│       self_check.tool_calls = 4
│       self_check.phases = 5
│
│   [if score < 0.7, reinvestigate spawns here]
│   ├── agent.phase.reinvestigate
│   │   └── agent.tool.dynatrace.query_traces  [retry]
│   └── agent.phase.self_check  [retry]
│
└── agent.phase.final_decision
        incident.resolution = confirmed
        incident.closed = true
```

---

## Demo

### Prerequisites

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set DYNATRACE_TENANT_URL, DYNATRACE_API_TOKEN, GOOGLE_CLOUD_PROJECT
```

### Step 1: Start the OTel Collector

```bash
# Download otelcol-contrib from:
# https://github.com/open-telemetry/opentelemetry-collector-releases/releases

DYNATRACE_API_TOKEN=<your_token> \
  otelcol-contrib --config=config/otel-collector-config.yaml
```

Or with Docker:

```bash
docker run --rm -p 4317:4317 -p 4318:4318 \
  -v "$(pwd)/config:/etc/otel" \
  -e DYNATRACE_API_TOKEN=$DYNATRACE_API_TOKEN \
  otel/opentelemetry-collector-contrib:latest \
  --config /etc/otel/otel-collector-config.yaml
```

### Step 2: Start the API

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Step 3: Trigger a Demo Incident

```bash
curl -X POST http://localhost:8000/handle-incident \
  -H "Content-Type: application/json" \
  -d '{"incident_id": "INC-404", "alert_text": "CPU spike on payment-gateway. 95% connections active. Latency >2s."}'
```

Or run the standalone demo script:

```bash
python tests/demo_run.py
```

### Step 4: Observe in Dynatrace

Live distributed traces:
```
https://roj78786.apps.dynatrace.com/ui/diagnostictools/purepaths
```

Filter by: `service.name = reliability-agent` or `incident.id = INC-404`

Import the command center dashboard:
```bash
# Dynatrace Settings → Dashboards → Import
config/dynatrace_dashboards.json
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Agent Framework | Google Agent Development Kit (ADK) |
| Agent Platform | Vertex AI Agent Platform |
| LLM | Gemini 2.5 Pro (`gemini-2.5-pro`) |
| API Layer | FastAPI + Uvicorn |
| Observability SDK | OpenTelemetry Python SDK |
| Telemetry Transport | OTLP HTTP (traces + metrics) |
| Collector | OpenTelemetry Collector Contrib |
| Observability Backend | Dynatrace |
| HTTP Client | httpx (async-capable, timeout-safe) |
| GCP Logging | google-cloud-logging v2 |
| Infrastructure | Cloud Run + Terraform |

---

## Deployment

```bash
cd infra && terraform apply
```

The Terraform configuration provisions Cloud Run, IAM bindings, and environment variable injection for GCP and Dynatrace credentials.

---

## Roadmap

**Autonomous remediation intelligence**
Replace static runbooks with a reinforcement-learned remediation policy that weights actions by historical success rates, surfaced as span attributes.

**MCP tool integration**
Extend the tool layer via Model Context Protocol to support heterogeneous observability backends — Prometheus, Grafana, PagerDuty — without agent-layer coupling.

**Kubernetes incident response**
Native `kubectl` tooling for pod restarts, deployment rollbacks, and HPA scaling events, with admission webhook integration for pre-execution approval gates.

**Multi-agent coordination**
Decompose complex incidents across specialized sub-agents (network, database, application) coordinated through a root orchestrator, with cross-agent trace propagation preserving a unified trace context.

**Predictive incident triggering**
Replace reactive webhook triggering with anomaly-score-based preemptive investigation, using Dynatrace Davis AI scores as agent invocation signals.

**Telemetry-driven self-improvement**
Aggregate self-check scores, tool call patterns, and resolution outcomes across incidents to identify systematic investigation gaps and update the agent's instruction prompt dynamically.

---

## Why This Matters

The deployment of autonomous AI agents into production infrastructure is accelerating. The operational frameworks for governing them are not keeping pace.

Infrastructure observability answers: *Is the system healthy?*
Application observability answers: *Is the service behaving correctly?*

Neither answers: *Is the AI agent that manages both of those things reasoning correctly?*

ReliabilityAgent is an argument — in working code — that this question is answerable. That AI agent behavior can be instrumented, exported, and analyzed with the same precision applied to distributed systems. That confidence scoring, tool coverage, phase sequencing, and recursive self-correction are not aspirational AI safety properties — they are operational engineering properties, achievable today with OpenTelemetry and a Dynatrace backend.

The future of AI systems is not just autonomous execution. It is **observable autonomy**.

ReliabilityAgent transforms observability from passive monitoring into active AI self-governance.

---

*Built for the Google Cloud Rapid Agent Hackathon — Dynatrace Sponsor Track.*
*Google ADK · Vertex AI · Gemini 2.5 Pro · OpenTelemetry · Dynatrace*
