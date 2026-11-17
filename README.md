# OneLab — Payments Reconciliation Dashboard

A payments reconciliation tool that finds gaps between an internal transaction ledger and bank settlement files.

## What it detects

| Gap Type | Description |
|---|---|
| NEXT_MONTH_SETTLEMENT | Jan transaction settled in Feb — missing from month-end close |
| ROUNDING_DIFF | Sub-$1 amount mismatch from float precision vs bank 2dp rounding |
| AGGREGATE_ROUNDING | Batch of txns that individually match but diverge when summed |
| DUPLICATE_SETTLEMENT | Same transaction settled more than once |
| ORPHAN_REFUND | Negative transaction with no settlement record |
| UNSETTLED | Transaction exists in ledger but bank has no settlement |

## Run locally

```bash
python generate_data.py   # generate demo CSV data
python app.py             # start server at http://localhost:5000
```

## Run tests

```bash
python -m pytest test_reconcile.py -v
```

## Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
3. Railway auto-detects Python, reads `Procfile`, sets `PORT` automatically
4. Done — live URL in ~2 minutes

## Files

```
app.py              HTTP server + API endpoints (pure stdlib, no dependencies)
dashboard.html      Frontend — tabs, charts, filters, export
reconcile.py        Reconciliation engine
generate_data.py    Synthetic test data generator (63 txns, 6 gap types planted)
test_reconcile.py   27 unit + integration tests
transactions.csv    Generated transaction ledger
settlements.csv     Generated bank settlement file
Procfile            Railway start command
runtime.txt         Python version pin
```

## Assumptions

- Amounts in USD; internal ledger stores raw floats, bank rounds to 2 decimal places
- Refunds are negative-amount transactions
- Report month is January 2024
- Datetimes are naive UTC
- Duplicate = same txn_id appears more than once in settlements file
