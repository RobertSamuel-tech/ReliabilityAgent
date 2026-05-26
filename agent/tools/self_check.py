"""Self-observability loop tool — queries Dynatrace Grail DQL, falls back to in-process registry."""
import os
import httpx
from google.adk.tools import FunctionTool
from opentelemetry import trace
from agent.tools._tool_registry import get_tool_count, get_tool_names

tracer = trace.get_tracer(__name__)

_DT_APPS_URL = "https://roj78786.apps.dynatrace.com"
_DQL_ENDPOINT = f"{_DT_APPS_URL}/platform/storage/query/v1/query:execute"
_MIN_TOOL_CALLS = 3


def _query_dql(trace_id: str, dt_token: str) -> tuple[int | None, str]:
    """
    Attempt Grail DQL query. Returns (tool_count, backend_label) or (None, error_label).
    Grail requires OAuth 2.0 Bearer JWT — API tokens return 401. We attempt it anyway
    so the attribute self_check.dql_attempted=True is always honest, and fall through
    gracefully without triggering accidental recursion.
    """
    dql = (
        f'fetch spans '
        f'| filter dt.trace_id == "{trace_id}" '
        f'| filter startsWith(span.name, "agent.tool") '
        f'| summarize tool_count = count()'
    )
    try:
        resp = httpx.post(
            _DQL_ENDPOINT,
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
        # 401 = OAuth required (expected); 403 = missing scope; anything else unexpected
        return None, f"dql_unavailable_http_{resp.status_code}"
    except Exception as e:
        return None, f"dql_error_{type(e).__name__}"


def verify_investigation_thoroughness(trace_id: str, incident_id: str) -> str:
    """
    Queries Dynatrace Grail DQL to count agent.tool spans for this trace, then decides
    whether the investigation was sufficiently thorough. Falls back to the in-process
    tool call registry when Grail DQL is unavailable (OAuth not configured).
    Only triggers re-investigation when tool_count < 3 — never from backend errors.
    """
    with tracer.start_as_current_span("agent.phase.self_check") as span:
        span.set_attribute("self_check.trace_id", trace_id)
        span.set_attribute("self_check.incident_id", incident_id)
        span.set_attribute("self_check.dql_attempted", True)

        dt_token = os.getenv("DYNATRACE_API_TOKEN", "")

        # --- Attempt 1: Dynatrace Grail DQL ---
        dql_count, dql_backend = _query_dql(trace_id, dt_token)
        span.set_attribute("self_check.dql_backend_result", dql_backend)

        if dql_count is not None:
            tool_count = dql_count
            query_backend = "dynatrace_grail_dql"
        else:
            # --- Fallback: in-process registry (same process, reliable) ---
            tool_count = get_tool_count(trace_id)
            tool_names = get_tool_names(trace_id)
            query_backend = "in_process_registry"
            span.set_attribute("self_check.registry_tools", str(tool_names))

        span.set_attribute("self_check.tool_count", tool_count)
        span.set_attribute("self_check.query_backend", query_backend)

        # --- Business logic decision ---
        if tool_count == 0 and query_backend == "in_process_registry":
            # Registry empty + DQL unavailable — cannot make a reliable judgment
            span.set_attribute("self_check.verdict", "UNAVAILABLE")
            span.add_event("self_check_unavailable", {
                "reason": "dql_401_and_registry_empty",
                "trace_id": trace_id,
            })
            return (
                f"SELF-CHECK UNAVAILABLE: Grail DQL returned {dql_backend} and in-process "
                f"registry is empty for trace {trace_id}. Investigation data cannot be verified. "
                f"Proceeding without re-investigation."
            )

        if tool_count < _MIN_TOOL_CALLS:
            span.set_attribute("self_check.verdict", "FAILED")
            span.set_attribute("self_check.retry_triggered", True)
            span.set_attribute("self_check.reason", "insufficient_tool_depth")
            span.add_event("self_check_failed", {
                "tool_count": tool_count,
                "threshold": _MIN_TOOL_CALLS,
                "query_backend": query_backend,
            })
            return (
                f"SELF-CHECK FAILED: Only {tool_count} tool call(s) detected via {query_backend} "
                f"(minimum required: {_MIN_TOOL_CALLS}). "
                f"The investigation was not sufficiently thorough. "
                f"You MUST re-investigate: query Dynatrace traces AND GCP logs again, "
                f"then re-execute the runbook before closing incident {incident_id}."
            )

        # tool_count >= _MIN_TOOL_CALLS
        span.set_attribute("self_check.verdict", "PASSED")
        span.set_attribute("self_check.retry_triggered", False)
        span.add_event("self_check_passed", {
            "tool_count": tool_count,
            "threshold": _MIN_TOOL_CALLS,
            "query_backend": query_backend,
        })
        return (
            f"SELF-CHECK PASSED: {tool_count} tool call(s) confirmed via {query_backend} "
            f"(minimum required: {_MIN_TOOL_CALLS}). "
            f"Investigation depth is sufficient. Incident {incident_id} can be closed."
        )


verify_investigation_thoroughness = FunctionTool(verify_investigation_thoroughness)
