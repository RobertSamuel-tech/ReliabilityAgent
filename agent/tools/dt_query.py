"""Dynatrace query tool."""
import os
import httpx
from opentelemetry import trace
from google.adk.tools import FunctionTool

tracer = trace.get_tracer(__name__)

def query_dynatrace_traces(query: str, time_from: str = "now-1h", time_to: str = "now") -> str:
    """
    Query Dynatrace distributed traces using DQL.
    Use this to find errors, latency spikes, or service dependencies.
    """
    with tracer.start_as_current_span("agent.tool.dynatrace.query_traces") as span:
        span.set_attribute("tool.name", "dynatrace.query_traces")
        span.set_attribute("tool.input.query", query)
        span.set_attribute("tool.input.time_from", time_from)

        dt_url = os.getenv("DYNATRACE_TENANT_URL", "")
        token = os.getenv("DYNATRACE_API_TOKEN", "")

        if not dt_url or not token:
            span.set_status(trace.StatusCode.ERROR, "Missing Dynatrace credentials")
            return "ERROR: DYNATRACE_TENANT_URL or DYNATRACE_API_TOKEN not set"

        dql = f'fetch traces | filter contains(name, "{query}") | from {time_from} | to {time_to} | limit 20'

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{dt_url}/api/v2/dql/query",
                    headers={"Authorization": f"Api-Token {token}", "Content-Type": "application/json"},
                    json={"query": dql}
                )
                span.set_attribute("tool.status_code", resp.status_code)

                if resp.status_code != 200:
                    span.set_status(trace.StatusCode.ERROR, f"Dynatrace query failed: {resp.status_code}")
                    return f"ERROR: {resp.text[:500]}"

                data = resp.json()
                records = data.get("records", [])
                span.set_attribute("tool.result.count", len(records))
                return f"Found {len(records)} trace records for query '{query}'"
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            return f"ERROR: {str(e)}"

query_dynatrace_traces = FunctionTool(query_dynatrace_traces)
