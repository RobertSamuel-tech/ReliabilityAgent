"""Self-observability loop tool."""
import os
import httpx
from google.adk.tools import FunctionTool
from opentelemetry import trace

tracer = trace.get_tracer(__name__)
DYNATRACE_URL = os.getenv("DYNATRACE_TENANT_URL", "")
DYNATRACE_TOKEN = os.getenv("DYNATRACE_API_TOKEN", "")

def verify_investigation_thoroughness(trace_id: str, incident_id: str) -> str:
    """
    CRITICAL: Use this tool AFTER remediation.
    Queries Dynatrace for this agent's OWN trace to verify the investigation
    was thorough enough. If score < 0.7, the agent must re-investigate.
    """
    with tracer.start_as_current_span("agent.phase.self_check") as span:
        span.set_attribute("self_check.trace_id", trace_id)
        span.set_attribute("self_check.incident_id", incident_id)

        if not DYNATRACE_URL or not DYNATRACE_TOKEN:
            span.set_status(trace.StatusCode.ERROR, "Missing Dynatrace credentials")
            return "ERROR: Cannot self-check without DYNATRACE_TENANT_URL and DYNATRACE_API_TOKEN"

        try:
            resp = httpx.get(
                f"{DYNATRACE_URL}/api/v2/traces/{trace_id}",
                headers={"Authorization": f"Api-Token {DYNATRACE_TOKEN}"},
                timeout=30.0
            )

            span.set_attribute("self_check.api_status", resp.status_code)

            if resp.status_code != 200:
                span.set_attribute("self_check.error", resp.text[:500])
                return f"SELF-CHECK ERROR: Cannot fetch trace {trace_id} (HTTP {resp.status_code})"

            data = resp.json()
            spans = data.get("spans", [])

            tool_calls = [s for s in spans if "agent.tool" in s.get("name", "")]
            phases = [s for s in spans if "agent.phase" in s.get("name", "")]

            checks = {
                "min_3_tools": len(tool_calls) >= 3,
                "queried_traces": any("dynatrace.query_traces" in s.get("name", "") for s in tool_calls),
                "queried_logs": any("gcp.query_logs" in s.get("name", "") for s in tool_calls),
                "queried_metrics": any("dynatrace.query_metrics" in s.get("name", "") for s in tool_calls),
                "all_phases": len(phases) >= 4,
                "high_confidence": any(
                    float(s.get("attributes", {}).get("diagnosis.confidence", 0)) >= 0.8
                    for s in spans
                ),
            }

            passed = sum(checks.values())
            total = len(checks)
            score = passed / total if total > 0 else 0.0

            span.set_attribute("self_check.score", score)
            span.set_attribute("self_check.tool_calls", len(tool_calls))
            span.set_attribute("self_check.phases", len(phases))

            if score >= 0.7:
                span.set_attribute("self_check.verdict", "SUFFICIENT")
                return f"SELF-CHECK PASSED ({passed}/{total}). Investigation is thorough. Closing incident {incident_id}."
            else:
                span.set_attribute("self_check.verdict", "INSUFFICIENT")
                failed = [k for k, v in checks.items() if not v]
                return f"SELF-CHECK FAILED ({passed}/{total}). Missing: {failed}. You MUST re-investigate before closing."
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            return f"SELF-CHECK ERROR: {str(e)}"

verify_investigation_thoroughness = FunctionTool(verify_investigation_thoroughness)
