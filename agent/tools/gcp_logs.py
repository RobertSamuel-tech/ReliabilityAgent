"""GCP Cloud Logging query tool."""
import os
from google.cloud import logging_v2
from google.adk.tools import FunctionTool
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def query_gcp_logs(filter_str: str, project_id: str = None, hours: int = 1) -> str:
    """
    Query Google Cloud Logging for logs matching a filter.
    Use this to find application errors, stack traces, or audit events.
    """
    with tracer.start_as_current_span("agent.tool.gcp.query_logs") as span:
        span.set_attribute("tool.name", "gcp.query_logs")
        span.set_attribute("tool.input.filter", filter_str)
        span.set_attribute("tool.input.hours", hours)

        project = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if not project:
            span.set_status(trace.StatusCode.ERROR, "Missing GCP project")
            return "ERROR: GOOGLE_CLOUD_PROJECT not set"

        try:
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

            if not entries:
                return "No log entries found matching filter."

            results = []
            for entry in entries[:10]:
                payload = entry.text_payload or entry.json_payload or str(entry)
                results.append(f"[{entry.timestamp}] {payload[:200]}")

            return "\n".join(results)
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            return f"ERROR: {str(e)}"

query_gcp_logs = FunctionTool(query_gcp_logs)
