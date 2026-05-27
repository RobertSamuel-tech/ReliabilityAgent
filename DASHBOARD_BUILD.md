# ReliabilityAgent ROI Command Center — Dashboard Build Guide

> **Why manual build?**
> Dynatrace dashboard JSON import is version-sensitive and tenant-specific.
> The only zero-error path is: build manually → export from your live tenant → commit that file.

---

## Step 1 — Open Dynatrace

1. Navigate to your tenant:
   ```
   https://roj78786.apps.dynatrace.com
   ```
2. Log in with your credentials.
3. In the left nav, click **Dashboards**.
4. Click **+ Create dashboard** (top right).
5. Name it:
   ```
   ReliabilityAgent ROI Command Center
   ```

---

## Step 2 — Create Tiles

Add the following 6 tiles in order. For each Data Explorer tile: click **Add tile → Data Explorer**, configure as shown, then click **Pin to dashboard**.

---

### TILE 1 — Incidents Handled

| Setting | Value |
|---|---|
| Visualization | Single value |
| Source | Data Explorer |
| Metric | `builtin:service.requestCount` |
| Filter | `service.name = reliability-agent` |
| Aggregation | SUM |
| Title | `Incidents Handled` |

**What it shows:** Total number of incidents the AI reliability agent has processed. This is the top-line throughput proof for judges.

---

### TILE 2 — Recursive Recovery Rate

| Setting | Value |
|---|---|
| Visualization | Single value |
| Source | Data Explorer |
| Metric | `builtin:service.requestCount` |
| Filter | `service.name = reliability-agent` AND `span.name = agent.phase.reinvestigate` |
| Aggregation | SUM |
| Title | `Recursive Recovery Rate` |

**What it shows:** How many times the self-check loop triggered a reinvestigation cycle. Non-zero here is the proof the recursive loop is live.

---

### TILE 3 — Avg AI Cost per Incident

| Setting | Value |
|---|---|
| Visualization | Single value |
| Source | Data Explorer |
| Metric | `builtin:service.response.time` |
| Filter | `service.name = reliability-agent` |
| Aggregation | AVG |
| Title | `Avg AI Cost per Incident` |

**What it shows:** Average investigation execution time as a proxy for AI effort and cost. Pair this verbally with the `llm.cost.usd` span attribute visible in Distributed Traces.

---

### TILE 4 — Self-Check Failures

| Setting | Value |
|---|---|
| Visualization | Pie chart |
| Source | Data Explorer |
| Metric | `builtin:service.requestCount` |
| Filter | `service.name = reliability-agent` AND `span.name = agent.phase.self_check` |
| Split by | `span.status` |
| Title | `Self-Check Failures` |

**What it shows:** Pass/fail breakdown of the agent's self-verification loop. A non-trivial failure slice proves the agent is actually catching its own mistakes.

---

### TILE 5 — Span Latency Trend

| Setting | Value |
|---|---|
| Visualization | Line chart |
| Source | Data Explorer |
| Metric | `builtin:service.response.time` |
| Filter | `service.name = reliability-agent` |
| Aggregation | AVG |
| Time window | Last 2 hours |
| Title | `Span Latency Trend` |

**What it shows:** Investigation latency over time. Spikes correlate with reinvestigation cycles — visible proof that complex incidents trigger deeper analysis.

---

### TILE 6 — Agent Architecture

| Setting | Value |
|---|---|
| Visualization | Markdown |
| Title | `Agent Architecture` |

**Content — paste exactly:**

```
## ReliabilityAgent

**Self-Observing AI SRE**

- Vertex AI + ADK + Gemini
- OpenTelemetry → Collector → Dynatrace
- Recursive self-check with graceful degradation
- Cost attribution per span

**Architecture:**
Agent → OTel SDK → Collector → Dynatrace → Agent queries back
```

**What it shows:** Architecture summary for judge walkthrough. Gives context without leaving the dashboard.

---

## Step 3 — Arrange Layout

Arrange tiles in a **2×3 executive grid**:

```
┌──────────────────┬──────────────────┬──────────────────┐
│  Incidents       │  Recursive       │  Avg AI Cost     │
│  Handled         │  Recovery Rate   │  per Incident    │
│  [Single value]  │  [Single value]  │  [Single value]  │
├──────────────────┴──────────────────┼──────────────────┤
│  Self-Check Failures                │  Span Latency    │
│  [Pie chart]                        │  Trend [Line]    │
├─────────────────────────────────────┴──────────────────┤
│  Agent Architecture [Markdown — full width]            │
└────────────────────────────────────────────────────────┘
```

To resize: drag the bottom-right corner of each tile. Aim for equal-width columns in the top two rows.

---

## Step 4 — Save the Dashboard

1. Click **Done** (top right of the edit toolbar).
2. The dashboard name `ReliabilityAgent ROI Command Center` is saved automatically.
3. Verify all 6 tiles show data (may take 60–90 seconds after the first incident fires).

---

## Step 5 — Export Dashboard JSON

1. Open the dashboard **⋮ menu** (top right).
2. Click **Export** → **Export as JSON** (exact label may vary by tenant version).
3. Save the downloaded file.
4. Replace the placeholder in the repo:
   ```
   config/dynatrace_dashboards.json
   ```
   with the exported file — this is now the canonical, importable version tied to your tenant.
5. Commit:
   ```bash
   git add config/dynatrace_dashboards.json
   git commit -m "Add live-exported Dynatrace dashboard JSON"
   ```

---

## Step 6 — Demo Execution

### Before your demo slot (T-5 minutes)

```bash
# Fire the canned P1 incident to seed live data
curl -X POST http://localhost:8000/demo/incident
```

Wait **30–60 seconds**, then refresh the dashboard. You should see:
- **Incidents Handled** counter increment
- **Self-Check Failures** pie slice appear
- **Span Latency Trend** show a spike for the investigation window

### During the demo — the "holy sh*t" moment

1. Open the dashboard in one browser tab.
2. Open **Distributed Tracing** (left nav → Distributed Traces) in a second tab.
3. Fire another incident live:
   ```bash
   curl -X POST http://localhost:8000/demo/incident
   ```
4. Switch to Distributed Tracing. Filter by `service.name = reliability-agent`.
5. Click into the trace. Walk the judges through the spans:
   - `agent.incident.handle` — the outer root span (full investigation)
   - `agent.phase.investigate` — initial diagnosis
   - `agent.phase.self_check` — the agent verifying its own work
   - `agent.phase.reinvestigate` *(if triggered)* — the recursive retry loop
6. Point out `llm.cost.usd` and `llm.tokens.input/output` as span attributes — **no other hackathon team is tracking AI cost at the span level**.
7. Switch back to the dashboard. The counters have already updated.

**Talking point:** "This agent doesn't just diagnose — it checks its own reasoning, queries Dynatrace for confirmation, and re-investigates if the evidence doesn't hold up. The dashboard you're looking at is the agent's own observability data."

---

## Step 7 — Devpost Screenshot Instructions

Capture these screenshots for the submission:

| Screenshot | What to capture |
|---|---|
| **1 — Full dashboard** | All 6 tiles visible, live data, timestamp visible |
| **2 — Distributed Trace** | Waterfall view of a full `agent.incident.handle` trace with all child spans expanded |
| **3 — Span detail** | Single span showing `llm.cost.usd`, `llm.model`, `incident.id` attributes |
| **4 — Self-check span** | `agent.phase.self_check` span with `self_check.verdict` and `self_check.retry_triggered` attributes |
| **5 — Terminal + dashboard** | Side-by-side: terminal showing `curl` output + dashboard updating in real time |

**Recommended tool:** Use browser full-page screenshot or Windows `Win + Shift + S` for cropped captures.

---

## Tiles to Highlight in Demo Video

| Priority | Tile | Why it lands |
|---|---|---|
| **#1** | Distributed Trace waterfall | Proves the recursive loop is real, not a claim |
| **#2** | Self-Check Failures (Pie) | Visual proof the agent catches its own errors |
| **#3** | Recursive Recovery Rate | Non-zero = the loop fired = differentiator confirmed |
| **#4** | Span detail with `llm.cost.usd` | No other team tracks AI cost at span granularity |
| **#5** | Incidents Handled (Single value) | Simple throughput proof for non-technical judges |
