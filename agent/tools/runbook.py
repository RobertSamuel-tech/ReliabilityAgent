"""Remediation runbook execution tool."""
import os
from google.adk.tools import FunctionTool
from opentelemetry import trace
from agent.tools._tool_registry import record_tool_call

tracer = trace.get_tracer(__name__)

def execute_runbook(runbook_name: str, target_service: str, parameters: dict = None) -> str:
    """
    Execute a remediation runbook against a target service.
    Examples: 'restart-service', 'scale-deployment', 'flush-cache'.
    """
    with tracer.start_as_current_span("agent.tool.runbook.execute") as span:
        ctx = span.get_span_context()
        record_tool_call(format(ctx.trace_id, "032x") if ctx.is_valid else "", "runbook.execute")
        span.set_attribute("tool.name", "runbook.execute")
        span.set_attribute("runbook.name", runbook_name)
        span.set_attribute("runbook.target", target_service)
        span.set_attribute("runbook.human_approved", True)

        params = parameters or {}
        span.set_attribute("runbook.parameters", str(params))

        # For hackathon demo, simulate execution. In production, call Cloud Deploy or Cloud Run API.
        result = f"✅ Executed runbook '{runbook_name}' on {target_service}. Status: SUCCESS. Parameters: {params}"
        span.set_attribute("runbook.status", "success")
        return result

execute_runbook = FunctionTool(execute_runbook)
