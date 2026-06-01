"""
Integration tests — verify the full application without mocking core logic.

All assertions are written against the actual implementation, not assumptions.
"""
import importlib
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent

# Directories to skip when grepping project source files
_EXCLUDE_DIRS = {".venv", ".venv311", ".venv312", "node_modules", ".git", "__pycache__", ".claude", ".pytest_cache"}


def _read_source(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def _grep_project(pattern: str, exclude_file: str | None = None) -> list[tuple[Path, int, str]]:
    """
    Walk every text file under PROJECT_ROOT and return (path, lineno, line) tuples
    where the line matches *pattern* (case-insensitive). Skips _EXCLUDE_DIRS trees.
    """
    hits: list[tuple[Path, int, str]] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        # Skip excluded directory trees
        if any(excl in path.parts for excl in _EXCLUDE_DIRS):
            continue
        # Skip caller-specified file
        if exclude_file and path.name == exclude_file:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line, re.IGNORECASE):
                hits.append((path, lineno, line.strip()))
    return hits


# ── 1. Import hygiene ─────────────────────────────────────────────────────────

def test_imports():
    """All core modules import without raising."""
    modules = [
        "agent.tools.self_check",
        "agent.tools.dt_query",
        "agent.tools.gcp_logs",
        "agent.models.schemas",
        "main",
    ]
    for mod in modules:
        imported = importlib.import_module(mod)
        assert imported is not None, f"import {mod} returned None"


# ── 2. OpenAI eradication ─────────────────────────────────────────────────────

def test_no_openai():
    """Zero project-owned files reference 'openai' (case-insensitive)."""
    hits = _grep_project(r"openai", exclude_file="test_integration.py")
    assert hits == [], (
        f"Found {len(hits)} 'openai' reference(s) — must be removed:\n"
        + "\n".join(f"  {p.relative_to(PROJECT_ROOT)}:{n}: {l}" for p, n, l in hits)
    )


# ── 3. No fake / modulo verdict logic ────────────────────────────────────────

def test_no_fake_logic():
    """self_check.py must not contain modulo-based fraud or call-count faking."""
    src = _read_source("agent/tools/self_check.py")
    assert "% 2" not in src, (
        "Found '% 2' (modulo-based fake verdict) in agent/tools/self_check.py"
    )
    assert "_call_count" not in src, (
        "Found '_call_count' (fake counter) in agent/tools/self_check.py"
    )


# ── 4. No mock / fake data in tool files ─────────────────────────────────────

def test_no_mocks():
    """dt_query.py and gcp_logs.py must not contain mock or fake data patterns."""
    for rel in ("agent/tools/dt_query.py", "agent/tools/gcp_logs.py"):
        src = _read_source(rel).lower()
        assert "mock" not in src, f"Found 'mock' in {rel}"
        assert "fake" not in src, f"Found 'fake' in {rel}"


# ── 5. FastAPI route coverage ─────────────────────────────────────────────────

def test_app_routes():
    """FastAPI app exposes every required endpoint path."""
    from main import app

    registered = {route.path for route in app.routes}
    required = {
        "/health",
        "/autopsy/start",
        "/autopsy/{incident_id}/status",
        "/autopsy/{incident_id}/feedback",
        "/ui",
    }
    missing = required - registered
    assert not missing, (
        f"Missing route(s): {missing}\n"
        f"Registered paths: {sorted(registered)}"
    )


# ── 6. Pydantic schema round-trips ────────────────────────────────────────────

def test_schemas():
    """All Pydantic models instantiate and serialize correctly."""
    from agent.models.schemas import (
        AutopsyState,
        HumanFeedback,
        Hypothesis,
        IncidentInput,
    )

    # IncidentInput
    incident = IncidentInput(
        incident_id="TEST-001",
        service_name="cart-service",
        time_range="-1h",
        description="CPU spike",
    )
    d = incident.model_dump()
    assert d["incident_id"] == "TEST-001"
    assert d["service_name"] == "cart-service"
    assert d["time_range"] == "-1h"
    assert d["description"] == "CPU spike"

    # HumanFeedback — both valid actions
    for action in ("approve", "redirect"):
        fb = HumanFeedback(action=action, feedback="looks correct")
        assert fb.model_dump()["action"] == action

    # Hypothesis
    h = Hypothesis(
        summary="DB pool exhausted",
        confidence="HIGH",
        evidence=["99% connections active", "P99 latency >4s"],
        full_analysis="Connection pool saturated due to runaway query.",
    )
    hd = h.model_dump()
    assert hd["confidence"] == "HIGH"
    assert len(hd["evidence"]) == 2

    # AutopsyState — default status is "collecting", hypothesis starts None
    state = AutopsyState(
        incident_id="TEST-001",
        service_name="cart-service",
        time_range="-1h",
    )
    sd = state.model_dump()
    assert sd["status"] == "collecting"
    assert sd["hypothesis"] is None
    assert sd["postmortem"] is None

    # AutopsyState with nested hypothesis
    state2 = AutopsyState(
        incident_id="TEST-002",
        service_name="api-gateway",
        time_range="-2h",
        status="awaiting_review",
        hypothesis=h,
    )
    sd2 = state2.model_dump()
    assert sd2["hypothesis"]["confidence"] == "HIGH"
    assert sd2["status"] == "awaiting_review"


# ── 7. Real self-check verdict via registry ───────────────────────────────────

def test_self_check_real():
    """
    verify_investigation_thoroughness returns FAILED for <3 tool calls and
    PASSED for >=3 tool calls. Uses the in-process registry as truth source.

    _MIN_TOOL_CALLS == 3 (from agent/tools/self_check.py).
    FunctionTool stores the original callable under .func.
    """
    import agent.tools._tool_registry as reg
    from agent.tools import self_check as sc_module

    # Retrieve the raw Python function from the FunctionTool wrapper
    ft = sc_module.verify_investigation_thoroughness
    fn = ft.func
    assert callable(fn), "FunctionTool.func is not callable"

    # ── 2 tool calls → FAILED ───────────────────────────────────────────────
    trace_fail = "integ-test-trace-fail-0002"
    reg.record_tool_call(trace_fail, "dynatrace.query_traces")
    reg.record_tool_call(trace_fail, "gcp.query_logs")

    result_fail = fn(trace_id=trace_fail, incident_id="INC-INTEG-FAIL")

    assert isinstance(result_fail, dict), f"Expected dict, got {type(result_fail)}"
    assert result_fail["verdict"] == "FAILED", (
        f"Expected FAILED with 2 tool calls (threshold=3), got: {result_fail}"
    )
    assert result_fail["tool_count"] == 2
    assert result_fail["backend"] == "in_process_registry"

    # ── 4 tool calls → PASSED ───────────────────────────────────────────────
    trace_pass = "integ-test-trace-pass-0004"
    for tool in (
        "dynatrace.query_traces",
        "gcp.query_logs",
        "runbook.execute",
        "self_check.verify",
    ):
        reg.record_tool_call(trace_pass, tool)

    result_pass = fn(trace_id=trace_pass, incident_id="INC-INTEG-PASS")

    assert isinstance(result_pass, dict), f"Expected dict, got {type(result_pass)}"
    assert result_pass["verdict"] == "PASSED", (
        f"Expected PASSED with 4 tool calls (threshold=3), got: {result_pass}"
    )
    assert result_pass["tool_count"] == 4
    assert result_pass["backend"] == "in_process_registry"
