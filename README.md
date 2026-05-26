# ReliabilityAgent

**A self-observing Site Reliability AI agent built for the Google Cloud Rapid Agent Hackathon.**

## The Problem
AI agents diagnose production incidents, but who watches the agent? Without observability, agents are black boxes that can miss root causes, hallucinate fixes, or skip investigation steps.

## The Solution
ReliabilityAgent diagnoses and remediates incidents by querying Dynatrace traces, GCP logs, and metrics — then **queries its own distributed trace in Dynatrace** to verify it investigated thoroughly. A recursive self-observability loop that makes the agent accountable.

## Architecture 

┌─────────────┐     ┌──────────────────────┐     ┌─────────────┐
│   Alert     │────▶│  ReliabilityAgent    │────▶│  Dynatrace  │
│  Webhook    │     │  (Vertex AI + ADK)   │     │  (Backend)  │
└─────────────┘     └──────────────────────┘     └─────────────┘
│                            │
▼                            │
┌───────────────┐                    │
│  OTel Collector│──────────────────┘
│  (BindPlane)   │     (Self-check queries
└───────────────┘      its own trace)


## Tech Stack
- **Agent Framework:** Google Agent Development Kit (ADK) on Vertex AI Agent Platform
- **LLM:** Gemini 2.5 Pro
- **Observability:** OpenTelemetry → BindPlane → Dynatrace
- **Infrastructure:** Cloud Run, Terraform

## Quick Start
1. Copy `.env.example` to `.env` and fill in your Dynatrace/GCP credentials
2. Start the OTel Collector: `otelcol-contrib --config=config/otel-collector-config.yaml`
3. Install deps: `pip install -r requirements.txt`
4. Run: `uvicorn main:app --reload`
5. Trigger test incident: `curl -X POST http://localhost:8000/handle-incident -H "Content-Type: application/json" -d '{"incident_id":"inc-001","alert_text":"CPU spike on prod-db-01"}'`

## The Self-Observability Loop
After remediation, the agent calls `verify_investigation_thoroughness(trace_id)` which:
1. Queries the Dynatrace API for its own trace
2. Counts tool calls, checks if logs/traces/metrics were all queried
3. Scores investigation thoroughness (0.0 - 1.0)
4. If score < 0.7, forces re-investigation

## Dashboards
Import `config/dynatrace_dashboards.json` into Dynatrace for the live Command Center.

## Deployment
```bash
cd infra && terraform apply
```
