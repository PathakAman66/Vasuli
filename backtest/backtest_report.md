# Vasuli Backtest Report

Batch size: 55 events

## Policy: `cost_aware_ladder`

- Contacts made: 55
- Resolved: 30/55 (54.5%)
- Gross recovered: Rs 172,070.00
- Outreach cost: Rs 502.40
- **Net recovered: Rs 171,567.60**
- Channel breakdown: {'email': 24, 'auto_retry': 21, 'human_escalation': 10}

## Policy: `aggressive`

- Contacts made: 55
- Resolved: 35/55 (63.6%)
- Gross recovered: Rs 218,365.00
- Outreach cost: Rs 414.00
- **Net recovered: Rs 217,951.00**
- Channel breakdown: {'whatsapp': 32, 'auto_retry': 16, 'human_escalation': 7}

## Verdict

On raw net-recovered-INR, `aggressive` comes out ahead (Rs 217,951.00). That number alone would argue for always being aggressive.

But this is exactly the honest-metrics trap the buildathon brief warns against: `aggressive` earns that extra revenue by skipping the 24h pre-debit notice cooldown compliance check entirely (see `backtest/policies.py::aggressive_decide` -- it never calls `check_pre_debit_alert_window`). It contacts customers sooner and more often than the e-mandate framework's notice requirement allows.

`cost_aware_ladder` is Vasuli's actual default for exactly this reason: it earns ~21% less net revenue on this batch, but every single action it takes passes the same compliance checks a human auditor would apply. The gap between the two numbers above is the visible price of staying compliant -- reported here rather than hidden, per the brief's 'honest metrics' bar.