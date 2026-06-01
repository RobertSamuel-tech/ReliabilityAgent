import os
import httpx
from google.adk.tools import FunctionTool
from opentelemetry import trace
from observability.logger import get_logger
from agent.tools._tool_registry import record_tool_call

tracer = trace.get_tracer(__name__)
logger = get_logger("agent.tools")


def query_gcp_logs(filter_str: str, project_id: str = None, hours: int = 1) -> dict:
    with tracer.start_as_current_span("agent.tool.gcp.query_logs") as span:
        ctx = span.get_span_context()
        record_tool_call(format(ctx.trace_id, "032x") if ctx.is_valid else "", "gcp.query_logs")
        span.set_attribute("tool.name", "gcp.query_logs")
        span.set_attribute("tool.input.filter", filter_str)

        project = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "")

        if not project:
            error_msg = "Missing required configuration: GOOGLE_CLOUD_PROJECT not set and project_id not provided"
            span.set_status(trace.StatusCode.ERROR, error_msg)
            span.set_attribute("tool.error", error_msg)
            logger.info("Tool gcp.query_logs failed: missing project",
                        extra={"tool.name": "gcp.query_logs", "error": error_msg})
            return {"success": False, "error": error_msg, "data": []}

        try:
            from google.cloud import logging_v2
            client = logging_v2.LoggingServiceV2Client()
            resource_names = [f"projects/{project}"]
            filter_full = f'{filter_str} AND timestamp >= "{hours}h"'

            resp = client.list_log_entries(
                resource_names=resource_names,
                filter=filter_full,
                order_by="timestamp desc",
                page_size=20
            )
            entries = list(resp)
            span.set_attribute("tool.result.count", len(entries))

            results = []
            for e in entries[:10]:
                try:
                    payload = str(e.text_payload or e.json_payload or "")[:200]
                    results.append({
                        "timestamp": str(e.timestamp),
                        "payload": payload,
                        "severity": str(e.severity) if hasattr(e, "severity") else None,
                        "log_name": e.log_name if hasattr(e, "log_name") else None,
                    })
                except UnicodeEncodeError:
                    results.append({
                        "timestamp": str(e.timestamp),
                        "payload": "<unicode_error>",
                        "severity": None,
                        "log_name": None,
                    })

            logger.info("Tool gcp.query_logs completed",
                        extra={"tool.name": "gcp.query_logs",
                               "tool.result.count": len(entries)})
            return {
                "success": True,
                "data": results,
                "metadata": {
                    "count": len(entries),
                    "filter": filter_str,
                    "project": project,
                    "hours": hours,
                },
            }

        except Exception as e:
            error_msg = f"GCP Cloud Logging request failed: {type(e).__name__}: {e}"
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, error_msg)
            span.set_attribute("tool.error", str(e)[:200])
            logger.info("Tool gcp.query_logs exception",
                        extra={"tool.name": "gcp.query_logs", "error": error_msg})
            return {"success": False, "error": error_msg, "data": []}


query_gcp_logs = FunctionTool(query_gcp_logs)
