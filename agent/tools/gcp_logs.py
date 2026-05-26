import os
import httpx
from google.adk.tools import FunctionTool
from opentelemetry import trace
from observability.logger import get_logger
from agent.tools._tool_registry import record_tool_call

tracer = trace.get_tracer(__name__)
logger = get_logger("agent.tools")


def query_gcp_logs(filter_str: str, project_id: str = None, hours: int = 1) -> str:
    with tracer.start_as_current_span("agent.tool.gcp.query_logs") as span:
        ctx = span.get_span_context()
        record_tool_call(format(ctx.trace_id, "032x") if ctx.is_valid else "", "gcp.query_logs")
        span.set_attribute("tool.name", "gcp.query_logs")
        span.set_attribute("tool.input.filter", filter_str)

        project = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "")

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

            if entries:
                results = []
                for e in entries[:10]:
                    try:
                        payload = str(e.text_payload or e.json_payload or "")[:200]
                        results.append(f"[{e.timestamp}] {payload}")
                    except UnicodeEncodeError:
                        results.append(f"[{e.timestamp}] <unicode_error>")

                logger.info(
                    "Tool gcp.query_logs completed",
                    extra={"tool.name": "gcp.query_logs", "tool.result.count": len(entries)},
                )
                return "\n".join(results)
        except Exception as e:
            span.set_attribute("tool.error", str(e)[:200])
            span.set_status(trace.StatusCode.ERROR, "GCP auth failed, using mock fallback")

        mock_logs = [
            f"[{hours}h ago] ERROR: Connection pool exhausted on db-master",
            f"[{hours}h ago] WARN: 95/100 DB connections active",
            f"[{hours}h ago] ERROR: Query timeout after 30s",
            f"[{hours}h ago] INFO: Auto-scaling triggered",
            f"[{hours}h ago] ERROR: Health check failed on service/api-v2"
        ]
        span.set_attribute("tool.result.count", len(mock_logs))
        span.set_attribute("tool.mock_data", True)

        logger.info(
            "Tool gcp.query_logs completed (mock fallback)",
            extra={"tool.name": "gcp.query_logs", "tool.result.count": len(mock_logs)},
        )
        return "MOCK DATA (GCP auth unavailable):\n" + "\n".join(mock_logs)


query_gcp_logs = FunctionTool(query_gcp_logs)
