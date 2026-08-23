# Vasuli — Explainable, Compliance-Bound Revenue Recovery Agent

*Built for the Razorpay AI Buildathon 2026 — AI Revenue Recovery track*

> Vasuli doesn't just retry failed payments — it explains every decision,
> stays inside RBI/NPCI-modeled compliance rules, and picks the cheapest
> channel that will actually work, so the number it reports is **net**
> recovered revenue, not a flattering gross figure.

---

## The problem

Revenue leaks out of a merchant's business in two quiet ways:
1. **Failed recurring payments** — UPI Autopay / subscription mandates that
   fail, most often (per RBI reporting) because the customer's account
   simply didn't have the balance at debit time.
2. **Checkout abandonment** — a payment link is created and never completed.

Naive "retry every N hours" bots either annoy customers into churning, or
quietly break e-mandate notice rules. Vasuli treats recovery as a **bounded
decision problem**, not a blind retry loop.

## The bar this project targets

From the buildathon brief: *"Don't just identify the problem. Show measured
money recovered across a batch, with compliant escalation, stopping rules,
and an audit trail."* Every section below maps directly to one clause of
that sentence.

## Architecture

```
Synthetic batch (55 events)          Razorpay test-mode API
         │                                    │
         └───────────────┬────────────────────┘
                          ▼
                 Detection engine
              (flags unresolved events)
                          ▼
        Claude — error-message parser ONLY
   (unstructured gateway text → root_cause + confidence)
                          ▼
        Deterministic rules engine (no LLM here)
   ├─ AFA threshold check      (>Rs 15,000 → never silent-retry)
   ├─ Pre-debit cooldown check (24h notice window)
   ├─ Max-attempts check       (3 attempts, then → exception list)
   └─ Confidence floor check   (low confidence → human escalation)
                          ▼
              Bounded executor
     (only ever runs a rules-engine-approved action)
                          ▼
        Audit log (every stage, every reasoning)
                          ▼
              Dashboard (net ₹, funnel, drill-down)

   ── separately, offline ──
   Backtest engine: replays the SAME batch under two policies
   (cost-aware ladder vs. aggressive) → backtest_report.md
```

### The one design decision to know cold

**Claude is used in exactly one place**: turning a raw, unstructured gateway
error string (e.g. `"NPCI Error: Insufficient Balance (Code: 51)"`) into a
structured `root_cause` label + confidence score. That is a genuine
text-classification problem — hardcoded string matching is brittle across
gateways, and this is exactly the kind of unstructured-signal parsing LLMs
are good at.

Every decision *after* that — is a retry allowed, which channel, what it
costs, whether to stop — is plain, deterministic Python in `app/rules/`.
The LLM can produce a **wrong label**. It can never produce a **wrong money
action**, because the rules engine sits between it and the executor and
re-validates everything against hard caps regardless of what the LLM said.
This is provable, not just claimed: `tests/test_rules.py` exercises the
rules engine with zero LLM calls, and you can feed it a maximally-confident
wrong diagnosis and watch it still refuse to silently retry above the AFA
threshold (`test_above_afa_threshold_always_escalates_to_human`).

If the LLM call fails entirely (no API key, network error, bad JSON), the
pipeline **does not crash** — `app/diagnosis/llm_parser.py` falls back to a
keyword heuristic and lowers its own confidence, which in turn makes the
rules engine more conservative (escalates to a human instead of guessing).
This is the "one failure handled gracefully" the brief asks for, and it's
exercised by every batch run without an API key.

## Compliance modeling (be precise about what this is)

Two rules in `app/rules/compliance.py` are modeled from **publicly reported**
RBI/NPCI e-mandate framework behaviour:
- Recurring debits above **₹15,000** are reported to require full
  Additional Factor of Authentication — Vasuli routes these to human
  escalation rather than a silent auto-retry, unconditionally.
- E-mandate rules require advance notice before a retry debit — Vasuli
  enforces a **24-hour cooldown** between attempts on the same event.

**Honest caveat, stated plainly so it doesn't need to be asked in the
interview**: these are illustrative, plain-language approximations built
from public reporting for a buildathon demo, not a verified legal
compliance product. The point being demonstrated is the *pattern* —
compliance constraints as hard, testable code rather than a suggestion to
an LLM — not a claim of regulatory certification.

## Real Razorpay API verification

This isn't a mocked response — `app/razorpay_client/client.py` calls the
actual Razorpay test-mode API when `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`
are set. Verified output from a real test-mode payment link creation call:

```
python -c "from dotenv import load_dotenv; load_dotenv(); from app.razorpay_client.client import create_test_payment_link; print(create_test_payment_link(999, 'Vasuli test recovery', 'cust_demo'))"

{'id': 'plink_TTHHr3POlLbxby', 'short_url': 'https://rzp.io/rzp/z04rfHk',
 'status': 'created', 'amount': 99900, 'currency': 'INR',
 'description': 'Vasuli test recovery', ...}
```

`short_url` is a real, working Razorpay test-mode payment link
(`https://rzp.io/rzp/z04rfHk`) — not a placeholder. If no keys are set,
the same function degrades to a clearly-marked mock response instead of
crashing, so the rest of the app still works without live credentials
(see the "graceful degradation" note above).

## Robustness: deliberately trying to break it

`robustness/stress_test.py` runs 7 adversarial cases against the rules
engine specifically designed to make it do something unsafe: approve a
silent high-value retry, ignore the cooldown, trust an overconfident wrong
diagnosis, or crash on malformed input.

```bash
PYTHONPATH=. python robustness/stress_test.py
```

Current result: **7/7 held**, including a boundary-amount attack (exactly
₹1 over the AFA threshold with a 99%-confidence diagnosis) and a
same-instant replay attack. Full report: `robustness/robustness_report.md`.
This is separate from `tests/test_rules.py`, which proves correctness on
expected inputs — this proves the same engine holds up against inputs
designed to find its edges.

## The backtest: an honest, non-cherry-picked result

`backtest/run_backtest.py` replays the exact same 55-event batch under two
policies and reports both. The result is genuinely instructive rather than
a foregone conclusion:

| Policy | Resolved | Gross recovered | Outreach cost | **Net recovered** |
|---|---|---|---|---|
| `cost_aware_ladder` (Vasuli's default) | 54.5% | ₹172,070 | ₹502 | **₹171,568** |
| `aggressive` | 63.6% | ₹218,365 | ₹414 | **₹217,951** |

The aggressive policy actually nets **more** revenue on this batch. It earns
that by skipping the 24-hour pre-debit cooldown check entirely and
escalating to WhatsApp immediately. `cost_aware_ladder` stays the default
anyway — the ~21% revenue gap is the visible, measured price of staying
inside the compliance rule, reported here instead of hidden. That trade-off,
made explicit rather than picked silently, is the actual point of building
a backtest engine instead of just a demo. Full report: `backtest/backtest_report.md`.

## Project structure

```
vasuli/
├── README.md
├── requirements.txt
├── .env.example
├── data/
│   ├── generate_synthetic.py   # builds the 55-event batch (seeded, reproducible)
│   └── synthetic_batch.json
├── app/
│   ├── main.py                 # FastAPI app + pipeline orchestration
│   ├── models.py                # shared Pydantic schemas
│   ├── db.py                    # SQLite persistence + audit log
│   ├── detection/detector.py
│   ├── diagnosis/llm_parser.py  # the ONLY file that calls Claude
│   ├── rules/
│   │   ├── compliance.py        # AFA threshold, pre-debit cooldown
│   │   ├── caps.py               # max attempts, confidence floor
│   │   └── channel_selector.py   # deterministic decision core
│   ├── executor/actions.py      # bounded execution, simulated sends
│   ├── audit/logger.py
│   └── razorpay_client/client.py  # test-mode Razorpay SDK wrapper
├── backtest/
│   ├── policies.py               # aggressive vs cost_aware_ladder
│   ├── run_backtest.py
│   └── backtest_report.md        # generated
├── robustness/
│   ├── stress_test.py            # 7 adversarial cases against the rules engine
│   └── robustness_report.md      # generated
├── dashboard/index.html          # single-file dashboard, ledger/audit-stamp UI
└── tests/
    ├── test_rules.py             # 8 tests, zero LLM calls needed
    └── test_executor.py
```

## Running it

```bash
python -m venv venv && source venv/bin/activate     # optional but recommended
pip install -r requirements.txt

cp .env.example .env      # fill in ANTHROPIC_API_KEY (Razorpay keys optional)

python data/generate_synthetic.py     # generates data/synthetic_batch.json
pytest tests/ -v                      # 11 tests, all pass without any API key

uvicorn app.main:app --reload --port 8420
# open http://localhost:8420 and click "Run recovery batch"

PYTHONPATH=. python backtest/run_backtest.py   # writes backtest/backtest_report.md
```

The dashboard works even with **no API keys set at all** — the diagnosis
step falls back to a keyword heuristic and the pipeline runs end to end.
Set `ANTHROPIC_API_KEY` to see Claude's actual classification reasoning in
the audit trail instead of the heuristic fallback text.

## Measured results (this batch, seeded, reproducible)

- **55 events**, ₹293,845 total flagged at risk
- **Net recovered** (typical run): ₹120,000–165,000 depending on simulated
  outcome variance — every run is logged, nothing is cherry-picked
- **0 exceptions** on a fresh batch (max-attempts exhaustion only shows up
  on repeated runs against the same DB, which is itself demoable live)
- **11/11 unit tests pass**, all without any external API call

## Honest limitations

- Outcome simulation (`app/executor/actions.py`) uses illustrative success
  probabilities per channel/root-cause, not real observed conversion rates
  — there is no real customer contact in this build, by design (test-mode
  only, per the brief).
- Compliance rules are modeled from public reporting, not verified against
  the actual NPCI circular text — flagged explicitly above.
- WhatsApp/email sends are simulated (logged, not dispatched) — the brief's
  bar is bounded logic and an audit trail, not real message delivery.
- The Razorpay test-mode client (`app/razorpay_client/client.py`) is wired
  for payment-link creation and status fetch; it degrades to a mock
  response if no keys are set so the rest of the app still runs.

## What I'd build next with more time

- Real Razorpay webhook ingestion instead of a static synthetic batch
- A second LLM pass that cross-checks the rules engine's own compliance
  reasoning against the actual NPCI circular text (retrieval-grounded)
- Per-customer channel-preference learning (contextual bandit) instead of
  a fixed cause→channel mapping