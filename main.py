"""FastAPI entrypoint for ReliabilityAgent on Cloud Run."""
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from agent.core import ReliabilityAgent

app = FastAPI(title="ReliabilityAgent API", version="1.0.0")
agent = ReliabilityAgent()

class AlertPayload(BaseModel):
    incident_id: str
    alert_text: str

@app.post("/handle-incident")
async def handle_incident(payload: AlertPayload, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        agent.handle_incident,
        payload.incident_id,
        payload.alert_text
    )
    return {
        "status": "Agent investigating",
        "incident_id": payload.incident_id,
        "trace_id": "See Dynatrace Distributed Traces",
        "message": "Check Dynatrace for live trace progress."
    }

@app.get("/health")
def health():
    return {"status": "healthy", "observability": "active", "agent": "ready"}

@app.post("/demo/incident")
async def demo_incident(background_tasks: BackgroundTasks):
    """Pre-canned demo incident — fires INC-DEMO with a realistic P1 alert."""
    background_tasks.add_task(
        agent.handle_incident,
        "INC-DEMO-007",
        "Database connection pool exhausted on api-gateway. 95% connections active. P99 latency >4s. Auto-scaling not triggered. P1 incident."
    )
    return {
        "status": "Agent investigating",
        "incident_id": "INC-DEMO-007",
        "trace_id": "See Dynatrace Distributed Traces",
        "message": "Watch server logs and Dynatrace for live trace progress."
    }
