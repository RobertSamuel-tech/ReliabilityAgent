"""FastAPI entrypoint for ReliabilityAgent on Cloud Run."""
import asyncio
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.core import ReliabilityAgent
from agent.models.schemas import AutopsyState, HumanFeedback, Hypothesis, IncidentInput
from observability.setup import setup_telemetry
from observability.logger import get_logger

tracer, meter, _ = setup_telemetry()
logger = get_logger("main")

app = FastAPI(title="ReliabilityAgent API", version="1.0.0")
agent = ReliabilityAgent()

_STATIC_DIR = Path(__file__).parent / "static"

# ── In-memory autopsy store ───────────────────────────────────────────────────
AUTOPSY_STORE: dict[str, AutopsyState] = {}


# ── Static UI ─────────────────────────────────────────────────────────────────
@app.get("/ui", response_class=HTMLResponse)
async def serve_ui():
    try:
        return HTMLResponse(content=(_STATIC_DIR / "index.html").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="UI not found — ensure static/index.html exists")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Legacy alert model ────────────────────────────────────────────────────────
class AlertPayload(BaseModel):
    incident_id: str
    alert_text: str


# ── Existing endpoints (unchanged) ───────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "healthy", "observability": "active", "agent": "ready"}


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


@app.post("/demo/incident")
async def demo_incident(background_tasks: BackgroundTasks):
    """Pre-canned demo incident — fires INC-DEMO-007 with a realistic P1 alert."""
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


# ── Autopsy: evidence gathering ───────────────────────────────────────────────
async def _gather_evidence(state: AutopsyState) -> dict:
    """Collect real telemetry from Dynatrace and GCP; returns best-effort evidence dict."""
    evidence: dict = {}

    # Dynatrace traces (async HTTP)
    dt_url = os.getenv("DYNATRACE_TENANT_URL", "").rstrip("/")
    dt_token = os.getenv("DYNATRACE_API_TOKEN", "")
    if dt_url and dt_token:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{dt_url}/api/v2/traces",
                    headers={"Authorization": f"Api-Token {dt_token}"},
                    params={"from": state.time_range, "to": "now", "pageSize": 10},
                )
                if resp.status_code == 200:
                    traces = resp.json().get("traces", [])
                    evidence["dynatrace_traces"] = [
                        {
                            "traceId": t.get("traceId"),
                            "duration_ms": t.get("duration"),
                            "name": t.get("name"),
                            "status": t.get("status"),
                        }
                        for t in traces[:5]
                    ]
                else:
                    evidence["dynatrace_error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            evidence["dynatrace_error"] = f"{type(exc).__name__}: {exc}"
    else:
        evidence["dynatrace_error"] = "DYNATRACE_TENANT_URL or DYNATRACE_API_TOKEN not configured"

    # GCP Cloud Logging (sync SDK wrapped in thread)
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if project:
        def _fetch_gcp_logs():
            from google.cloud import logging_v2
            lc = logging_v2.LoggingServiceV2Client()
            entries = list(lc.list_log_entries(
                resource_names=[f"projects/{project}"],
                filter=f'resource.labels.service_name="{state.service_name}"',
                order_by="timestamp desc",
                page_size=10,
            ))
            return [
                {
                    "timestamp": str(e.timestamp),
                    "payload": str(e.text_payload or e.json_payload or "")[:200],
                }
                for e in entries[:5]
            ]
        try:
            evidence["gcp_logs"] = await asyncio.to_thread(_fetch_gcp_logs)
        except Exception as exc:
            evidence["gcp_error"] = f"{type(exc).__name__}: {exc}"
    else:
        evidence["gcp_error"] = "GOOGLE_CLOUD_PROJECT not configured"

    return evidence


# ── Autopsy: hypothesis synthesis ─────────────────────────────────────────────
async def _synthesize_hypothesis(state: AutopsyState, evidence: dict) -> Hypothesis:
    """Ask Gemini to build a structured root-cause hypothesis from gathered evidence."""
    from google import genai as _genai

    evidence_text = json.dumps(evidence, indent=2, default=str)[:3000]
    prompt = (
        f"You are a senior SRE performing a production incident analysis.\n\n"
        f"Incident ID: {state.incident_id}\n"
        f"Service:     {state.service_name}\n"
        f"Time Range:  {state.time_range}\n"
        f"Description: {state.description or 'No description provided'}\n\n"
        f"Evidence gathered:\n{evidence_text}\n\n"
        f"Return ONLY valid JSON matching this exact schema (no markdown fences, no extra text):\n"
        f'{{\n'
        f'  "summary": "<one sentence root-cause hypothesis>",\n'
        f'  "confidence": "<HIGH|MEDIUM|LOW>",\n'
        f'  "evidence": ["<key finding 1>", "<key finding 2>", "<key finding 3>"],\n'
        f'  "full_analysis": "<detailed 2-4 sentence analysis>"\n'
        f'}}'
    )

    def _call_gemini():
        client = _genai.Client()
        return client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            contents=prompt,
        )

    response = await asyncio.to_thread(_call_gemini)
    text = response.text.strip()

    # Strip markdown fences Gemini occasionally wraps responses in
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        confidence = str(data.get("confidence", "LOW")).upper()
        if confidence not in ("HIGH", "MEDIUM", "LOW"):
            confidence = "LOW"
        return Hypothesis(
            summary=str(data.get("summary", "Hypothesis unavailable")),
            confidence=confidence,
            evidence=[str(e) for e in data.get("evidence", [])],
            full_analysis=str(data.get("full_analysis", "")),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return Hypothesis(
            summary=f"Incident detected in {state.service_name} — structured parsing failed",
            confidence="LOW",
            evidence=["Gemini response could not be parsed as structured JSON"],
            full_analysis=text[:500],
        )


# ── Autopsy: postmortem generation ────────────────────────────────────────────
async def _generate_postmortem(state: AutopsyState) -> str:
    """Generate a markdown postmortem via Gemini; falls back to a template on any error."""
    h = state.hypothesis
    feedback = state.human_feedback.feedback if state.human_feedback else "None"
    evidence_bullets = "\n".join(f"- {e}" for e in (h.evidence if h else []))

    try:
        from google import genai as _genai

        prompt = (
            f"Write a production postmortem in markdown for this incident.\n\n"
            f"Incident ID: {state.incident_id}\n"
            f"Service: {state.service_name}\n"
            f"Root Cause: {h.summary if h else 'Unknown'}\n"
            f"Confidence: {h.confidence if h else 'N/A'}\n"
            f"Analysis: {h.full_analysis if h else ''}\n"
            f"Evidence:\n{evidence_bullets}\n"
            f"Operator Feedback: {feedback}\n\n"
            f"Include these sections exactly: "
            f"## Summary, ## Timeline, ## Root Cause, ## Impact, "
            f"## Remediation Steps, ## Action Items, ## Lessons Learned.\n"
            f"Be concise and technical. Do not use placeholder text."
        )

        def _call():
            client = _genai.Client()
            return client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
                contents=prompt,
            )

        response = await asyncio.to_thread(_call)
        return response.text

    except Exception as exc:
        logger.info(
            "Postmortem generation fell back to template",
            extra={"incident_id": state.incident_id, "error": str(exc)},
        )
        return (
            f"# Postmortem: {state.incident_id}\n\n"
            f"## Summary\n"
            f"Service `{state.service_name}` experienced a production incident.\n"
            f"{h.summary if h else 'Root cause analysis was not completed.'}\n\n"
            f"## Root Cause\n"
            f"{h.full_analysis if h else 'Analysis not available.'}\n\n"
            f"## Confidence\n"
            f"{h.confidence if h else 'N/A'}\n\n"
            f"## Evidence\n"
            f"{evidence_bullets or 'No evidence collected.'}\n\n"
            f"## Operator Feedback\n"
            f"{feedback}\n\n"
            f"## Status\n"
            f"Incident closed and approved by operator.\n"
        )


# ── Autopsy: investigation worker ─────────────────────────────────────────────
async def _run_autopsy(incident_id: str) -> None:
    """Background worker: gather evidence → synthesize hypothesis → set awaiting_review."""
    state = AUTOPSY_STORE.get(incident_id)
    if not state:
        return

    try:
        evidence = await _gather_evidence(state)
        state.evidence = evidence

        hypothesis = await _synthesize_hypothesis(state, evidence)
        state.hypothesis = hypothesis
        state.status = "awaiting_review"

        logger.info(
            "Autopsy awaiting review",
            extra={"incident_id": incident_id, "confidence": hypothesis.confidence},
        )
    except Exception as exc:
        state.status = "failed"
        state.error = f"{type(exc).__name__}: {exc}"
        logger.info(
            "Autopsy investigation failed",
            extra={"incident_id": incident_id, "error": str(exc)},
        )


# ── Autopsy endpoints ─────────────────────────────────────────────────────────
@app.post("/autopsy/start")
async def autopsy_start(payload: IncidentInput, background_tasks: BackgroundTasks):
    try:
        existing = AUTOPSY_STORE.get(payload.incident_id)
        if existing and existing.status not in ("failed", "completed"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Autopsy for '{payload.incident_id}' is already in progress "
                    f"(status: {existing.status!r}). Use a different incident_id or "
                    f"wait for the current one to complete."
                ),
            )

        state = AutopsyState(
            incident_id=payload.incident_id,
            service_name=payload.service_name,
            time_range=payload.time_range,
            description=payload.description,
            status="collecting",
        )
        AUTOPSY_STORE[payload.incident_id] = state

        background_tasks.add_task(_run_autopsy, payload.incident_id)

        logger.info(
            "Autopsy started",
            extra={"incident_id": payload.incident_id, "service": payload.service_name},
        )
        return {
            "status": "collecting",
            "incident_id": payload.incident_id,
            "review_url": f"/autopsy/{payload.incident_id}/status",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.info("autopsy_start error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/autopsy/{incident_id}/status")
async def autopsy_status(incident_id: str):
    try:
        state = AUTOPSY_STORE.get(incident_id)
        if not state:
            raise HTTPException(
                status_code=404,
                detail=f"No autopsy found for incident '{incident_id}'",
            )

        result = state.model_dump()

        if state.status == "awaiting_review" and state.hypothesis:
            result["question_for_human"] = (
                f"The agent identified a {state.hypothesis.confidence}-confidence hypothesis: "
                f'"{state.hypothesis.summary}" — '
                f"Approve to generate a postmortem, or redirect with feedback to reinvestigate."
            )

        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/autopsy/{incident_id}/feedback")
async def autopsy_feedback(
    incident_id: str,
    payload: HumanFeedback,
    background_tasks: BackgroundTasks,
):
    try:
        state = AUTOPSY_STORE.get(incident_id)
        if not state:
            raise HTTPException(
                status_code=404,
                detail=f"No autopsy found for incident '{incident_id}'",
            )

        if state.status != "awaiting_review":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Feedback only accepted when status is 'awaiting_review' "
                    f"(current: {state.status!r})"
                ),
            )

        state.human_feedback = payload

        if payload.action == "approve":
            postmortem = await _generate_postmortem(state)
            state.postmortem = postmortem
            state.status = "completed"
            logger.info("Autopsy approved", extra={"incident_id": incident_id})

        elif payload.action == "redirect":
            # Append operator feedback to the description so reinvestigation has context
            redirect_note = f"[Operator redirect: {payload.feedback}"
            if payload.additional_context:
                redirect_note += f" | Context: {payload.additional_context}"
            redirect_note += "]"
            state.description = f"{state.description or ''} {redirect_note}".strip()

            # Reset investigation state for the new pass
            state.status = "collecting"
            state.hypothesis = None

            background_tasks.add_task(_run_autopsy, incident_id)
            logger.info("Autopsy redirected", extra={"incident_id": incident_id})

        return state.model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Mount static files (after all route definitions) ─────────────────────────
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
