"""ReliabilityAgent core orchestration."""
import os
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from opentelemetry import trace

from agent.tools.dt_query import query_dynatrace_traces
from agent.tools.gcp_logs import query_gcp_logs
from agent.tools.runbook import execute_runbook
from agent.tools.self_check import verify_investigation_thoroughness
from agent.prompts import TRIAGE_PROMPT, INCIDENT_PROMPT_TEMPLATE
from observability.setup import setup_telemetry

tracer, meter = setup_telemetry()

# Custom metrics
token_counter = meter.create_counter("agent.tokens.total", description="Total LLM tokens consumed")
phase_duration = meter.create_histogram("agent.phase.duration_ms", description="Duration per phase")
incident_cost = meter.create_histogram("agent.incident.cost_usd", description="Cost per incident resolution")

class ReliabilityAgent:
    def __init__(self):
        self.tools = [
            query_dynatrace_traces,
            query_gcp_logs,
            execute_runbook,
            verify_investigation_thoroughness,
        ]

        self.agent = Agent(
            model=os.getenv("VERTEX_AI_MODEL", "gemini-2.5-pro"),
            name="reliability_agent",
            description="Self-observing SRE agent that diagnoses and remediates incidents",
            instruction=TRIAGE_PROMPT,
            tools=self.tools,
        )

        self.runner = Runner(
            agent=self.agent,
            app_name="reliability-agent",
            session_service=InMemorySessionService(),
        )

    async def handle_incident(self, incident_id: str, alert_text: str):
        with tracer.start_as_current_span("agent.incident.handle") as root_span:
            root_span.set_attribute("incident.id", incident_id)
            root_span.set_attribute("incident.severity", "P1")
            root_span.set_attribute("alert.text", alert_text)

            trace_id = format(root_span.get_span_context().trace_id, "032x")
            root_span.set_attribute("trace.id", trace_id)

            session = self.runner.session_service.create_session(
                app_name="reliability-agent",
                user_id="system"
            )

            content = INCIDENT_PROMPT_TEMPLATE.format(
                incident_id=incident_id,
                alert_text=alert_text,
                trace_id=trace_id
            )

            result = await self.runner.run_async(
                session_id=session.id,
                user_id="system",
                new_message=content
            )

            root_span.set_attribute("agent.result", str(result)[:500])
            return {
                "incident_id": incident_id,
                "trace_id": trace_id,
                "result": result,
            }
