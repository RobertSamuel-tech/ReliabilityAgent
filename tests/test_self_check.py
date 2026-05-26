"""Self-observability loop tests."""
import pytest
from agent.tools.self_check import verify_investigation_thoroughness

def test_self_check_missing_credentials():
    result = verify_investigation_thoroughness("fake-trace", "inc-001")
    assert "ERROR" in result
