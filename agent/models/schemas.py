from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class IncidentInput(BaseModel):
    incident_id: str
    service_name: str
    time_range: str = "-1h"
    description: Optional[str] = None


class HumanFeedback(BaseModel):
    action: Literal["approve", "redirect"]
    feedback: str
    additional_context: Optional[str] = None


class Hypothesis(BaseModel):
    summary: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    evidence: List[str] = []
    full_analysis: str = ""


class AutopsyState(BaseModel):
    incident_id: str
    service_name: str
    time_range: str
    description: Optional[str] = None
    status: Literal[
        "collecting",
        "awaiting_review",
        "approved",
        "redirected",
        "completed",
        "failed",
    ] = "collecting"
    hypothesis: Optional[Hypothesis] = None
    trace_id: Optional[str] = None
    evidence: Dict[str, Any] = {}
    human_feedback: Optional[HumanFeedback] = None
    postmortem: Optional[str] = None
    error: Optional[str] = None
