"""
Full recursive incident-investigation trace.
Emits a nested 5-phase span hierarchy with self-check and reinvestigation loop
to Dynatrace via OTLP HTTP.
"""
import os
import time

from dotenv import load_dotenv
load_dotenv()

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# ── TracerProvider ────────────────────────────────────────────────────────────
_endpoint = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"].rstrip("/") + "/v1/traces"
_token = os.environ["DYNATRACE_API_TOKEN"]

resource = Resource.create({
    "service.name": "reliability-agent",
    "service.version": "1.0.0",
    "deployment.environment": "production",
})

exporter = OTLPSpanExporter(
    endpoint=_endpoint,
    headers={"Authorization": f"Api-Token {_token}"},
)
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("reliability-agent.incident", "1.0.0")

# ── Incident constants ────────────────────────────────────────────────────────
INCIDENT_ID = "INC-404-RECURSE"
INCIDENT_SERVICE = "payment-gateway"
INCIDENT_SEVERITY = "P1"
LLM_MODEL = "gemini-1.5-pro"
CONFIDENCE_THRESHOLD = 0.8


# ── Tool simulators ───────────────────────────────────────────────────────────

def tool_query_logs():
    with tracer.start_as_current_span("agent.tool.query_logs") as span:
        span.set_attribute("incident.id", INCIDENT_ID)
        span.set_attribute("tool.name", "query_logs")
        span.set_attribute("tool.source", "gcp-cloud-logging")
        span.set_attribute("llm.model", LLM_MODEL)
        span.set_attribute("llm.tokens.input", 312)
        span.set_attribute("llm.tokens.output", 128)
        span.set_attribute("llm.cost.usd", 0.0014)

        print("    [tool:query_logs] Scanning GCP Cloud Logging for payment-gateway errors...")
        time.sleep(0.3)

        result_count = 47
        span.set_attribute("tool.result.count", result_count)
        span.set_attribute("tool.result.has_errors", True)
        span.set_attribute("tool.result.top_error", "DEADLINE_EXCEEDED in checkout.ProcessPayment")

        print(f"    [tool:query_logs] >> {result_count} entries | top error: DEADLINE_EXCEEDED")
        return result_count


def tool_query_traces(span_name="agent.tool.query_traces"):
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("incident.id", INCIDENT_ID)
        span.set_attribute("tool.name", span_name)
        span.set_attribute("tool.source", "dynatrace-distributed-traces")
        span.set_attribute("llm.model", LLM_MODEL)
        span.set_attribute("llm.tokens.input", 284)
        span.set_attribute("llm.tokens.output", 95)
        span.set_attribute("llm.cost.usd", 0.0011)

        print(f"    [tool:{span_name}] Querying Dynatrace distributed traces...")
        time.sleep(0.4)

        result_count = 23
        span.set_attribute("tool.result.count", result_count)
        span.set_attribute("tool.result.p99_latency_ms", 4872)
        span.set_attribute("tool.result.error_rate_pct", 34.7)

        print(f"    [tool:{span_name}] >> {result_count} traces | p99={4872}ms | error_rate=34.7%")
        return result_count


def tool_query_metrics():
    with tracer.start_as_current_span("agent.tool.query_metrics") as span:
        span.set_attribute("incident.id", INCIDENT_ID)
        span.set_attribute("tool.name", "query_metrics")
        span.set_attribute("tool.source", "dynatrace-metrics")
        span.set_attribute("llm.model", LLM_MODEL)
        span.set_attribute("llm.tokens.input", 198)
        span.set_attribute("llm.tokens.output", 74)
        span.set_attribute("llm.cost.usd", 0.0009)

        print("    [tool:query_metrics] Pulling CPU/memory/request-rate from Dynatrace...")
        time.sleep(0.25)

        result_count = 12
        span.set_attribute("tool.result.count", result_count)
        span.set_attribute("tool.result.cpu_spike_pct", 94.2)
        span.set_attribute("tool.result.memory_pressure", True)
        span.set_attribute("tool.result.request_drop_pct", 28.1)

        print(f"    [tool:query_metrics] >> {result_count} metrics | CPU spike 94.2% | req drop 28.1%")
        return result_count


# ── Main investigation ────────────────────────────────────────────────────────

def run_investigation():
    with tracer.start_as_current_span("agent.incident.handle") as root_span:

        # Root attributes
        root_span.set_attribute("incident.id", INCIDENT_ID)
        root_span.set_attribute("incident.service", INCIDENT_SERVICE)
        root_span.set_attribute("incident.severity", INCIDENT_SEVERITY)
        root_span.set_attribute("llm.model", LLM_MODEL)
        root_span.set_attribute("agent.version", "1.0.0")
        root_span.set_attribute("agent.pipeline", "recursive-self-check")

        root_span.add_event("incident_received", {
            "incident.id": INCIDENT_ID,
            "incident.service": INCIDENT_SERVICE,
            "incident.severity": INCIDENT_SEVERITY,
            "source": "pagerduty-webhook",
        })

        print(f"\n{'='*62}")
        print(f"  INCIDENT RECEIVED : {INCIDENT_ID}")
        print(f"  Service           : {INCIDENT_SERVICE}")
        print(f"  Severity          : {INCIDENT_SEVERITY}")
        print(f"{'='*62}\n")

        # ── Phase 1: TRIAGE ───────────────────────────────────────────────
        with tracer.start_as_current_span("agent.phase.triage") as triage_span:
            triage_span.set_attribute("incident.id", INCIDENT_ID)
            triage_span.set_attribute("incident.severity", INCIDENT_SEVERITY)
            triage_span.set_attribute("triage.affected_services", 3)
            triage_span.set_attribute("triage.on_call_notified", True)
            triage_span.set_attribute("triage.classification", "P1-CONFIRMED")
            triage_span.set_attribute("llm.model", LLM_MODEL)
            triage_span.set_attribute("llm.tokens.input", 156)
            triage_span.set_attribute("llm.tokens.output", 62)
            triage_span.set_attribute("llm.cost.usd", 0.0007)

            print("[TRIAGE] Classifying incident and determining blast radius...")
            time.sleep(0.2)
            print("[TRIAGE] P1 confirmed. 3 downstream services affected. On-call paged.")

        # ── Phase 2: DIAGNOSE ─────────────────────────────────────────────
        initial_confidence = 0.0
        evidence_total = 0

        with tracer.start_as_current_span("agent.phase.diagnose") as diagnose_span:
            diagnose_span.set_attribute("incident.id", INCIDENT_ID)
            diagnose_span.set_attribute("incident.service", INCIDENT_SERVICE)
            diagnose_span.set_attribute("llm.model", LLM_MODEL)
            diagnose_span.set_attribute("llm.tokens.input", 512)
            diagnose_span.set_attribute("llm.tokens.output", 248)
            diagnose_span.set_attribute("llm.cost.usd", 0.0032)

            diagnose_span.add_event("diagnosis_started", {
                "incident.id": INCIDENT_ID,
                "tools.planned": "query_logs,query_traces,query_metrics",
            })

            print("\n[DIAGNOSE] Launching multi-tool evidence collection...")

            log_count = tool_query_logs()
            trace_count = tool_query_traces()
            metric_count = tool_query_metrics()
            evidence_total = log_count + trace_count + metric_count

            # First-pass confidence is intentionally below threshold to trigger self-check
            initial_confidence = 0.63
            diagnose_span.set_attribute("investigation.confidence", initial_confidence)
            diagnose_span.set_attribute("diagnosis.root_cause_hypothesis",
                                        "DB connection pool exhaustion under payment surge")
            diagnose_span.set_attribute("diagnosis.evidence_count", evidence_total)

            print(f"\n[DIAGNOSE] Hypothesis  : DB connection pool exhaustion under payment surge")
            print(f"[DIAGNOSE] Evidence    : {evidence_total} data points collected")
            print(f"[DIAGNOSE] Confidence  : {initial_confidence:.0%}  (threshold: {CONFIDENCE_THRESHOLD:.0%})")

        # ── Phase 3: SELF-CHECK ───────────────────────────────────────────
        retry_triggered = False
        final_confidence = initial_confidence

        with tracer.start_as_current_span("agent.phase.self_check") as self_check_span:
            self_check_span.set_attribute("incident.id", INCIDENT_ID)
            self_check_span.set_attribute("investigation.confidence", initial_confidence)
            self_check_span.set_attribute("self_check.threshold", CONFIDENCE_THRESHOLD)
            self_check_span.set_attribute("llm.model", LLM_MODEL)
            self_check_span.set_attribute("llm.tokens.input", 420)
            self_check_span.set_attribute("llm.tokens.output", 185)
            self_check_span.set_attribute("llm.cost.usd", 0.0021)

            print(f"\n[SELF-CHECK] Evaluating investigation completeness...")
            print(f"[SELF-CHECK] Confidence : {initial_confidence:.0%} vs threshold {CONFIDENCE_THRESHOLD:.0%}")
            time.sleep(0.3)

            # Self-check score penalises incomplete upstream trace coverage
            self_check_score = round(initial_confidence * 0.95, 4)
            self_check_span.set_attribute("self_check.score", self_check_score)

            if initial_confidence < CONFIDENCE_THRESHOLD:
                retry_triggered = True
                self_check_span.set_attribute("self_check.retry_triggered", True)
                self_check_span.set_attribute("self_check.reason", "confidence_below_threshold")
                self_check_span.set_attribute("self_check.missing_coverage",
                                              "upstream_dependency_traces")

                self_check_span.add_event("self_check_failed", {
                    "self_check.score": self_check_score,
                    "self_check.confidence": initial_confidence,
                    "self_check.threshold": CONFIDENCE_THRESHOLD,
                    "self_check.gap": "upstream trace coverage incomplete",
                })

                print(f"[SELF-CHECK] FAILED  - score={self_check_score}")
                print(f"[SELF-CHECK] Missing : upstream dependency trace coverage")
                print(f"[SELF-CHECK] Action  : triggering reinvestigation phase")
            else:
                self_check_span.set_attribute("self_check.retry_triggered", False)
                self_check_span.set_attribute("self_check.reason", "confidence_sufficient")
                print(f"[SELF-CHECK] PASSED  - confidence sufficient, skipping retry")

        # ── Phase 4: REINVESTIGATE (triggered by self-check failure) ──────
        if retry_triggered:
            with tracer.start_as_current_span("agent.phase.reinvestigate") as reinvestigate_span:
                reinvestigate_span.set_attribute("incident.id", INCIDENT_ID)
                reinvestigate_span.set_attribute("investigation.retry_reason",
                                                 "self_check_confidence_below_threshold")
                reinvestigate_span.set_attribute("investigation.confidence_before_retry",
                                                 initial_confidence)
                reinvestigate_span.set_attribute("llm.model", LLM_MODEL)
                reinvestigate_span.set_attribute("llm.tokens.input", 634)
                reinvestigate_span.set_attribute("llm.tokens.output", 312)
                reinvestigate_span.set_attribute("llm.cost.usd", 0.0041)

                reinvestigate_span.add_event("reinvestigation_triggered", {
                    "trigger": "self_check_failure",
                    "incident.id": INCIDENT_ID,
                    "confidence_before": initial_confidence,
                    "strategy": "deep_upstream_trace_analysis",
                })

                print(f"\n[REINVESTIGATE] Expanding scope to upstream dependencies...")
                print(f"[REINVESTIGATE] Strategy: deep upstream trace analysis + retry query")

                retry_count = tool_query_traces("agent.tool.query_traces.retry")

                # Deeper investigation yields higher confidence
                final_confidence = 0.91
                confidence_delta = round(final_confidence - initial_confidence, 4)

                reinvestigate_span.set_attribute("investigation.confidence", final_confidence)
                reinvestigate_span.set_attribute("investigation.confidence_delta", confidence_delta)
                reinvestigate_span.set_attribute("reinvestigation.new_evidence",
                                                 "stripe-api-timeout-cascade")
                reinvestigate_span.set_attribute("reinvestigation.result_count", retry_count)

                print(f"[REINVESTIGATE] New evidence : Stripe API timeout cascade upstream of DB pool")
                print(f"[REINVESTIGATE] Confidence   : {final_confidence:.0%}  (+{confidence_delta:.0%} vs initial)")

        # ── Phase 5: FINAL DECISION ───────────────────────────────────────
        with tracer.start_as_current_span("agent.phase.final_decision") as decision_span:
            decision_span.set_attribute("incident.id", INCIDENT_ID)
            decision_span.set_attribute("incident.service", INCIDENT_SERVICE)
            decision_span.set_attribute("incident.severity", INCIDENT_SEVERITY)
            decision_span.set_attribute("investigation.confidence", final_confidence)
            decision_span.set_attribute("investigation.retry_triggered", retry_triggered)
            decision_span.set_attribute("llm.model", LLM_MODEL)
            decision_span.set_attribute("llm.tokens.input", 892)
            decision_span.set_attribute("llm.tokens.output", 445)
            decision_span.set_attribute("llm.cost.usd", 0.0068)
            decision_span.set_attribute("decision.action", "escalate_to_stripe_api_team")
            decision_span.set_attribute("decision.runbook", "RB-PAYMENT-UPSTREAM-TIMEOUT")
            decision_span.set_attribute("decision.root_cause",
                                        "Stripe API timeout cascade -> DB connection pool exhaustion")
            decision_span.set_attribute("decision.estimated_ttm_minutes", 25)

            decision_span.add_event("final_decision_generated", {
                "incident.id": INCIDENT_ID,
                "decision.confidence": final_confidence,
                "decision.action": "escalate_to_stripe_api_team",
                "decision.runbook": "RB-PAYMENT-UPSTREAM-TIMEOUT",
                "decision.root_cause": "Stripe API timeout cascade -> DB connection pool exhaustion",
            })

            print(f"\n[FINAL DECISION] Root cause : Stripe API timeout cascade")
            print(f"[FINAL DECISION] Detail     : upstream SLA breach -> DB connection pool exhausted")
            print(f"[FINAL DECISION] Action     : Escalate to Stripe API team + apply circuit breaker")
            print(f"[FINAL DECISION] Runbook    : RB-PAYMENT-UPSTREAM-TIMEOUT")
            print(f"[FINAL DECISION] Confidence : {final_confidence:.0%}")
            print(f"[FINAL DECISION] Est. TTM   : 25 minutes")

        # Finalise root span with aggregate totals
        total_tokens_in  = 156 + 512 + 420 + 634 + 892
        total_tokens_out = 62  + 248 + 185 + 312 + 445
        total_cost       = round(0.0007 + 0.0032 + 0.0021 + 0.0041 + 0.0068, 4)

        root_span.set_attribute("investigation.confidence", final_confidence)
        root_span.set_attribute("investigation.retry_triggered", retry_triggered)
        root_span.set_attribute("investigation.phases_executed", 5)
        root_span.set_attribute("llm.tokens.input", total_tokens_in)
        root_span.set_attribute("llm.tokens.output", total_tokens_out)
        root_span.set_attribute("llm.cost.usd", total_cost)

        trace_id = format(root_span.get_span_context().trace_id, "032x")

    return trace_id


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    trace_id = run_investigation()

    print(f"\n{'='*62}")
    print(f"  ROOT TRACE ID : {trace_id}")
    print(f"{'='*62}")
    print("\nFlushing telemetry to Dynatrace via OTLP HTTP...")
    provider.force_flush()
    print("Flush complete. Waiting 5 s for pipeline propagation...")
    time.sleep(5)
    print(f"\nVerify in Dynatrace -> Distributed Traces:")
    print(f"  Filter by trace ID : {trace_id}")
    print(f"  Or service name    : reliability-agent")
    print(f"  Expected waterfall : agent.incident.handle")
    print(f"    +-- agent.phase.triage")
    print(f"    +-- agent.phase.diagnose")
    print(f"    |   +-- agent.tool.query_logs")
    print(f"    |   +-- agent.tool.query_traces")
    print(f"    |   +-- agent.tool.query_metrics")
    print(f"    +-- agent.phase.self_check")
    print(f"    +-- agent.phase.reinvestigate")
    print(f"    |   +-- agent.tool.query_traces.retry")
    print(f"    +-- agent.phase.final_decision")
