"""ReliabilityAgent core orchestration."""
import os
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="litellm")
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.models.lite_llm import LiteLlm
from google.genai import types
from opentelemetry import trace

from agent.tools.dt_query import query_dynatrace_traces
from agent.tools.gcp_logs import query_gcp_logs
from agent.tools.runbook import execute_runbook
from agent.tools.self_check import verify_investigation_thoroughness
from agent.prompts import TRIAGE_PROMPT, INCIDENT_PROMPT_TEMPLATE
from observability.setup import setup_telemetry
from observability.logger import get_logger

tracer, meter, _ = setup_telemetry()
logger = get_logger("agent.core")

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

        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        openrouter_model = os.getenv("OPENROUTER_MODEL", "openrouter/openai/gpt-4o-mini")

        if openrouter_key:
            os.environ.setdefault("OPENROUTER_API_KEY", openrouter_key)
            self._model_name = openrouter_model
            model = LiteLlm(model=openrouter_model)
        else:
            self._model_name = os.getenv("VERTEX_AI_MODEL", "gemini-2.5-pro")
            model = self._model_name

        self.agent = Agent(
            model=model,
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

    def _extract_token_usage(self, result) -> dict:
        """Extract token usage from ADK event — handles Gemini and OpenAI/LiteLlm formats."""
        try:
            um = getattr(result, "usage_metadata", None)
            if um:
                # Gemini format
                inp = getattr(um, "prompt_token_count", None)
                out = getattr(um, "candidates_token_count", None)
                if inp is not None and out is not None:
                    return {"input": int(inp), "output": int(out)}
                # OpenAI-normalized format
                inp = getattr(um, "input_tokens", None) or getattr(um, "prompt_tokens", None)
                out = getattr(um, "output_tokens", None) or getattr(um, "completion_tokens", None)
                if inp is not None and out is not None:
                    return {"input": int(inp), "output": int(out)}
        except Exception:
            pass
        content_str = str(result)
        input_tokens = max(len(content_str) // 4, 200)
        return {"input": input_tokens, "output": input_tokens // 3}

    def _compute_cost(self, tokens: dict, model: str) -> float:
        """Compute USD cost based on model pricing."""
        inp, out = tokens["input"], tokens["output"]
        if "gpt-4o-mini" in model:
            return (inp * 0.00000015) + (out * 0.00000060)
        if "claude-3.5-sonnet" in model or "claude-3-5-sonnet" in model:
            return (inp * 0.000003) + (out * 0.000015)
        # Gemini 2.0 flash / default
        return (inp * 0.00000010) + (out * 0.00000040)

    async def handle_incident(self, incident_id: str, alert_text: str):
        with tracer.start_as_current_span("agent.incident.handle") as root_span:
            root_span.set_attribute("incident.id", incident_id)
            root_span.set_attribute("incident.severity", "P1")
            root_span.set_attribute("alert.text", alert_text)

            trace_id = format(root_span.get_span_context().trace_id, "032x")
            root_span.set_attribute("trace.id", trace_id)

            logger.info(
                "Incident investigation started",
                extra={"incident.id": incident_id, "trace.id": trace_id},
            )

            session = await self.runner.session_service.create_session(
                app_name="reliability-agent",
                user_id="system"
            )

            content = INCIDENT_PROMPT_TEMPLATE.format(
                incident_id=incident_id,
                alert_text=alert_text,
                trace_id=trace_id
            )

            result = None
            async for event in self.runner.run_async(
                session_id=session.id,
                user_id="system",
                new_message=types.Content(role="user", parts=[types.Part(text=content)])
            ):
                result = event

            tokens = self._extract_token_usage(result)
            model = self._model_name
            cost_usd = self._compute_cost(tokens, model)

            root_span.set_attribute("llm.tokens.input", tokens["input"])
            root_span.set_attribute("llm.tokens.output", tokens["output"])
            root_span.set_attribute("llm.model", model)
            root_span.set_attribute("llm.cost.usd", cost_usd)
            root_span.set_attribute("agent.result", str(result)[:500])

            token_counter.add(tokens["input"] + tokens["output"], {"model": model})
            incident_cost.record(cost_usd, {"incident.id": incident_id})

            logger.info(
                "Incident investigation complete",
                extra={
                    "incident.id": incident_id,
                    "trace.id": trace_id,
                    "llm.tokens.total": tokens["input"] + tokens["output"],
                    "llm.cost.usd": cost_usd,
                },
            )

            return {
                "incident_id": incident_id,
                "trace_id": trace_id,
                "result": result,
            }
