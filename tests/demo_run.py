import asyncio
import time
from observability.setup import setup_telemetry
from agent.core import ReliabilityAgent

tracer, meter = setup_telemetry()

async def main():
    agent = ReliabilityAgent()

    incident_id = "INC-DEMO-001"
    alert_text = "CPU spike on payment-gateway. 95% connections active. Latency >2s."

    print(f"🚨 Triggering incident: {incident_id}")
    print(f"Alert: {alert_text}")
    print("-" * 50)

    result = await agent.handle_incident(incident_id, alert_text)

    print("-" * 50)
    print(f"✅ Agent completed")
    print(f"Trace ID: {result.get('trace_id', 'unknown')}")
    print(f"Result: {str(result.get('result', ''))[:500]}")
    print("\nCheck Dynatrace Distributed Traces for live trace.")
    print(f"URL: https://roj78786.apps.dynatrace.com/ui/diagnostictools/purepaths")

if __name__ == "__main__":
    asyncio.run(main())
