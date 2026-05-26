# -*- coding: utf-8 -*-
"""Verify Dynatrace API and OTLP endpoint connectivity."""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

TENANT_URL = os.getenv("DYNATRACE_TENANT_URL", "").rstrip("/")
TOKEN = os.getenv("DYNATRACE_API_TOKEN", "")
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")

MASKED_TOKEN = TOKEN[:10] + "..." if len(TOKEN) > 10 else "***"
FAKE_TRACE_ID = "0" * 32

AUTH_HEADERS = {"Authorization": f"Api-Token {TOKEN}"}

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def check_env():
    print("=" * 60)
    print("Dynatrace Connectivity Verification")
    print("=" * 60)
    print(f"  Tenant URL  : {TENANT_URL}")
    print(f"  OTLP Base   : {OTEL_ENDPOINT}")
    print(f"  Token       : {MASKED_TOKEN}")
    print()

    missing = []
    if not TENANT_URL:
        missing.append("DYNATRACE_TENANT_URL")
    if not TOKEN:
        missing.append("DYNATRACE_API_TOKEN")
    if not OTEL_ENDPOINT:
        missing.append("OTEL_EXPORTER_OTLP_ENDPOINT")
    if missing:
        print(f"{FAIL} Missing env vars: {', '.join(missing)}")
        sys.exit(1)


def test_api_time():
    """Test 1 - basic API reachability via /api/v1/time."""
    print("-" * 60)
    print("Test 1: Basic API connectivity  (/api/v1/time)")
    url = f"{TENANT_URL}/api/v1/time"
    try:
        r = requests.get(url, headers=AUTH_HEADERS, timeout=10)
        if r.status_code == 200:
            print(f"{PASS}  HTTP 200 - API reachable")
            print(f"   Server time (epoch ms): {r.text.strip()}")
            return True
        else:
            print(f"{FAIL}  HTTP {r.status_code} - unexpected response")
            print(f"   Body: {r.text[:300]}")
            return False
    except Exception as e:
        print(f"{FAIL}  Connection error: {e}")
        return False


def test_otlp_endpoint():
    """Test 2 - OTLP ingest endpoint with empty payload.
    400 = auth OK, empty payload rejected (expected success).
    403 = auth failed / missing ingest permission -> stop.
    """
    print()
    print("-" * 60)
    print("Test 2: OTLP endpoint accessibility  (/api/v2/otlp/v1/traces)")
    url = f"{OTEL_ENDPOINT}/v1/traces"
    try:
        r = requests.post(
            url,
            headers={**AUTH_HEADERS, "Content-Type": "application/x-protobuf"},
            data=b"",
            timeout=10,
        )
        if r.status_code == 400:
            print(f"{PASS}  HTTP 400 - auth accepted, empty payload rejected (expected)")
            return True
        elif r.status_code == 200:
            print(f"{PASS}  HTTP 200 - OTLP endpoint accepted payload")
            return True
        elif r.status_code == 403:
            print(f"{FAIL}  HTTP 403 - auth failure or missing 'Ingest OpenTelemetry traces' permission")
            print(f"   Body: {r.text[:500]}")
            return False
        elif r.status_code == 401:
            print(f"{FAIL}  HTTP 401 - invalid or expired API token")
            print(f"   Body: {r.text[:500]}")
            return False
        else:
            print(f"{WARN}  HTTP {r.status_code} - unexpected response")
            print(f"   Body: {r.text[:300]}")
            return False
    except Exception as e:
        print(f"{FAIL}  Connection error: {e}")
        return False


def test_trace_lookup():
    """Test 3 - trace lookup API with a fake trace ID.
    404 = API reachable, trace not found (expected).
    """
    print()
    print("-" * 60)
    print("Test 3: Trace lookup API  (/api/v2/traces/<fake_id>)")
    url = f"{TENANT_URL}/api/v2/traces/{FAKE_TRACE_ID}"
    try:
        r = requests.get(url, headers=AUTH_HEADERS, timeout=10)
        if r.status_code == 404:
            print(f"{PASS}  HTTP 404 - API reachable, trace not found (expected)")
            return True
        elif r.status_code == 200:
            print(f"{PASS}  HTTP 200 - trace lookup returned data")
            return True
        elif r.status_code in (401, 403):
            print(f"{FAIL}  HTTP {r.status_code} - auth error on trace lookup")
            print(f"   Body: {r.text[:300]}")
            return False
        else:
            print(f"{WARN}  HTTP {r.status_code}")
            print(f"   Body: {r.text[:300]}")
            return False
    except Exception as e:
        print(f"{FAIL}  Connection error: {e}")
        return False


def main():
    check_env()

    api_ok = test_api_time()
    otlp_ok = test_otlp_endpoint()
    trace_ok = test_trace_lookup()

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  API time endpoint  : {'PASS' if api_ok   else 'FAIL'}")
    print(f"  OTLP ingest        : {'PASS' if otlp_ok  else 'FAIL'}")
    print(f"  Trace lookup API   : {'PASS' if trace_ok else 'FAIL'}")
    print()

    if not otlp_ok:
        print("OTLP auth failure detected - stopping.")
        print("Fix token permissions before running telemetry tests.")
        sys.exit(1)

    if api_ok and otlp_ok and trace_ok:
        print("All checks passed. Ready to run:  python tests/test_telemetry.py")
    else:
        print("One or more checks failed. Review output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
