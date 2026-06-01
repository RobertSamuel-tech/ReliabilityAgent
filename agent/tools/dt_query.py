import os
import httpx
from google.adk.tools import FunctionTool
from opentelemetry import trace
from observability.logger import get_logger
from agent.tools._tool_registry import record_tool_call

tracer = trace.get_tracer(__name__)
logger = get_logger("agent.tools")


def query_dynatrace_traces(query: str, time_from: str = "now-1h", time_to: str = "now") -> dict:
    with tracer.start_as_current_span("agent.tool.dynatrace.query_traces") as span:
        ctx = span.get_span_context()
        record_tool_call(format(ctx.trace_id, "032x") if ctx.is_valid else "", "dynatrace.query_traces")
        span.set_attribute("tool.name", "dynatrace.query_traces")
        span.set_attribute("tool.input.query", query)

        dt_url = os.getenv("DYNATRACE_TENANT_URL", "").rstrip("/")
        token = os.getenv("DYNATRACE_API_TOKEN", "")

        if not dt_url or not token:
            missing = []
            if not dt_url:
                missing.append("DYNATRACE_TENANT_URL")
            if not token:
                missing.append("DYNATRACE_API_TOKEN")
            error_msg = f"Missing required environment variables: {', '.join(missing)}"
            span.set_status(trace.StatusCode.ERROR, error_msg)
            span.set_attribute("tool.error", error_msg)
            logger.info("Tool dynatrace.query_traces failed: missing credentials",
                        extra={"tool.name": "dynatrace.query_traces", "error": error_msg})
            return {"success": False, "error": error_msg, "data": []}

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
                    logger.info("Tool dynatrace.query_traces completed",
                                extra={"tool.name": "dynatrace.query_traces",
                                       "tool.result.count": len(traces)})
                    return {
                        "success": True,
                        "data": [
                            {
                                "traceId": t.get("traceId"),
                                "duration_ms": t.get("duration"),
                                "name": t.get("name"),
                                "status": t.get("status"),
                            }
                            for t in traces
                        ],
                        "metadata": {
                            "count": len(traces),
                            "query": query,
                            "time_from": time_from,
                            "time_to": time_to,
                        },
                    }

                error_msg = f"Dynatrace API returned HTTP {resp.status_code}: {resp.text[:200]}"
                span.set_status(trace.StatusCode.ERROR, error_msg)
                span.set_attribute("tool.error", error_msg)
                logger.info("Tool dynatrace.query_traces failed",
                            extra={"tool.name": "dynatrace.query_traces",
                                   "tool.status_code": resp.status_code})
                return {"success": False, "error": error_msg, "data": []}

        except Exception as e:
            error_msg = f"Dynatrace API request failed: {type(e).__name__}: {e}"
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, error_msg)
            span.set_attribute("tool.error", error_msg[:200])
            logger.info("Tool dynatrace.query_traces exception",
                        extra={"tool.name": "dynatrace.query_traces", "error": error_msg})
            return {"success": False, "error": error_msg, "data": []}


query_dynatrace_traces = FunctionTool(query_dynatrace_traces)
