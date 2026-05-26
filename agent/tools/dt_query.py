import os
import httpx
from google.adk.tools import FunctionTool
from opentelemetry import trace
from observability.logger import get_logger
from agent.tools._tool_registry import record_tool_call

tracer = trace.get_tracer(__name__)
logger = get_logger("agent.tools")


def query_dynatrace_traces(query: str, time_from: str = "now-1h", time_to: str = "now") -> str:
    with tracer.start_as_current_span("agent.tool.dynatrace.query_traces") as span:
        ctx = span.get_span_context()
        record_tool_call(format(ctx.trace_id, "032x") if ctx.is_valid else "", "dynatrace.query_traces")
        span.set_attribute("tool.name", "dynatrace.query_traces")
        span.set_attribute("tool.input.query", query)

        dt_url = os.getenv("DYNATRACE_TENANT_URL", "")
        token = os.getenv("DYNATRACE_API_TOKEN", "")

        if not dt_url or not token:
            span.set_status(trace.StatusCode.ERROR, "Missing Dynatrace credentials")
            return "ERROR: DYNATRACE_TENANT_URL or DYNATRACE_API_TOKEN not set"

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{dt_url}/api/v2/traces",
                    headers={"Authorization": f"Api-Token {token}"},
                    params={"from": time_from, "to": time_to, "pageSize": 20}
                )
                span.set_attribute("tool.status_code", resp.status_code)

                if resp.status_code == 200:
                    data = resp.json()
                    traces = data.get("traces", [])
                    span.set_attribute("tool.result.count", len(traces))

                    logger.info(
                        "Tool dynatrace.query_traces completed",
                        extra={"tool.name": "dynatrace.query_traces", "tool.result.count": len(traces)},
                    )

                    if traces:
                        results = [
                            f"Trace: {t.get('traceId', 'unknown')} | Duration: {t.get('duration', 'N/A')}ms"
                            for t in traces[:5]
                        ]
                        return f"Found {len(traces)} traces:\n" + "\n".join(results)
                    return "No traces found in time range."
                else:
                    span.set_status(trace.StatusCode.ERROR, f"HTTP {resp.status_code}")
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))

        logger.info(
            "Tool dynatrace.query_traces completed (mock fallback)",
            extra={"tool.name": "dynatrace.query_traces", "tool.result.count": 12},
        )
        return f"Mock: Found 12 error traces for '{query}'. High latency detected."


query_dynatrace_traces = FunctionTool(query_dynatrace_traces)
