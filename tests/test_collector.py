"""Emit a test span through the local OTel Collector pipeline."""
import time
import os
from dotenv import load_dotenv

load_dotenv()

from observability.setup import setup_telemetry
from opentelemetry import trace

tracer, meter = setup_telemetry()

with tracer.start_as_current_span("test.collector.pipeline") as span:
    span.set_attribute("hackathon.track", "dynatrace")
    span.set_attribute("llm.tokens.input", 1000)
    span.set_attribute("llm.tokens.output", 500)
    span.set_attribute("test.source", "test_collector")

    trace_id = format(span.get_span_context().trace_id, "032x")
    print(f"Span started: test.collector.pipeline")
    print(f"Trace ID: {trace_id}")
    print(f"  hackathon.track  = dynatrace")
    print(f"  llm.tokens.input = 1000")
    print(f"  llm.tokens.output = 500")
    print(f"  llm.cost.usd will be computed by collector transform/cost processor")

print()
print("Waiting 3 seconds for BatchSpanProcessor flush...")
time.sleep(3)
print("Done. If the collector is running, check:")
print(f"  - Collector debug output (terminal running otelcol-contrib)")
print(f"  - ./output/traces.json")
print(f"  - Dynatrace: https://roj78786.live.dynatrace.com (Distributed Traces)")
