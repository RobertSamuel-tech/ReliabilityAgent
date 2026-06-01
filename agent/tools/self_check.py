"""Self-observability loop tool — verifies investigation thoroughness via in-process registry."""
import os
import httpx
from google.adk.tools import FunctionTool
from opentelemetry import trace
from agent.tools._tool_registry import get_tool_count, get_tool_names

tracer = trace.get_tracer(__name__)

_MIN_TOOL_CALLS = 3


def _dql_endpoint() -> str:
    tenant = os.getenv("DYNATRACE_TENANT_URL", "").rstrip("/")
    apps_host = tenant.replace(".live.dynatrace.com", ".apps.dynatrace.com")
    return f"{apps_host}/platform/storage/query/v1/query:execute"


def _query_dql(trace_id: str, dt_token: str) -> tuple[int | None, str]:
    """
    Attempt Grail DQL query for supplementary telemetry only.
    Returns (tool_count, backend_label) or (None, error_label).
    Grail requires OAuth 2.0 Bearer JWT — API tokens return 401; falls through gracefully.
    Result does NOT override the registry verdict.
    """
    dql = (
        f'fetch spans '
        f'| filter dt.trace_id == "{trace_id}" '
        f'| filter startsWith(span.name, "agent.tool") '
        f'| summarize tool_count = count()'
    )
    try:
        resp = httpx.post(
            _dql_endpoint(),
            headers={
                "Authorization": f"Bearer {dt_token}",
                "Content-Type": "application/json",
            },
            json={"query": dql, "requestTimeoutMilliseconds": 10000},
            timeout=15.0,
        )
        if resp.status_code == 200:
            records = resp.json().get("result", {}).get("records", [])
            count = int(records[0].get("tool_count", 0)) if records else 0
            return count, "dynatrace_grail_dql"
        return None, f"dql_unavailable_http_{resp.status_code}"
    except Exception as e:
        return None, f"dql_error_{type(e).__name__}"


def verify_investigation_thoroughness(trace_id: str, incident_id: str) -> dict:
    """
    Verifies investigation thoroughness using actual recorded tool calls from the
    in-process registry. Registry is the authoritative source of truth.
    A Grail DQL query is attempted as a supplementary data point only — its result
    is recorded as a span attribute but does not override the registry verdict.
    """
    with tracer.start_as_current_span("agent.phase.self_check") as span:
        span.set_attribute("self_check.trace_id", trace_id)
        span.set_attribute("self_check.incident_id", incident_id)

        # Authoritative source: in-process registry of actual tool calls
        tool_count = get_tool_count(trace_id)
        tool_names = get_tool_names(trace_id)
        backend = "in_process_registry"

        span.set_attribute("self_check.registry_tools", str(tool_names))

        # Supplementary: Grail DQL (recorded for telemetry; does not affect verdict)
        dt_token = os.getenv("DYNATRACE_API_TOKEN", "")
        dql_count, dql_backend = _query_dql(trace_id, dt_token)
        span.set_attribute("self_check.dql_attempted", True)
        span.set_attribute("self_check.dql_backend_result", dql_backend)
        if dql_count is not None:
            span.set_attribute("self_check.dql_tool_count", dql_count)

        # Verdict is driven entirely by the registry count
        verdict = "PASSED" if tool_count >= _MIN_TOOL_CALLS else "FAILED"

        span.set_attribute("self_check.tool_count", tool_count)
        span.set_attribute("self_check.backend", backend)
        span.set_attribute("self_check.verdict", verdict)
        span.set_attribute("self_check.retry_triggered", verdict == "FAILED")

        if verdict == "PASSED":
            span.add_event("self_check_passed", {
                "tool_count": tool_count,
                "threshold": _MIN_TOOL_CALLS,
                "backend": backend,
            })
        else:
            span.add_event("self_check_failed", {
                "tool_count": tool_count,
                "threshold": _MIN_TOOL_CALLS,
                "backend": backend,
                "reason": "insufficient_tool_calls" if tool_count > 0 else "trace_id_not_found",
            })

        return {
            "verdict": verdict,
            "tool_count": tool_count,
            "backend": backend,
        }


verify_investigation_thoroughness = FunctionTool(verify_investigation_thoroughness)
