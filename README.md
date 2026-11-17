# OneLab — Payments Reconciliation Dashboard

**Live Demo:** https://onelab-production.up.railway.app

A payments reconciliation tool that automatically finds gaps between an internal transaction ledger and bank settlement files. Built for the OneLab AI Fitness Assessment.

---

## The Problem

A payments company records every transaction the moment a customer pays. The bank batches and settles funds 1–2 days later. At month end, every transaction should have a matching settlement — same amount, same ID, settled within the same month.

They don't always match. This tool finds out why.

---

## Live Demo

Visit **https://onelab-production.up.railway.app** to see the dashboard running with demo data.

- **Reconciliation Gaps tab** — all detected gaps with risk scoring, filters, timeline chart, and CSV export
- **Full Ledger tab** — every transaction joined with its settlement, searchable and filterable

---

## What It Detects

| Gap Type | Severity | Description |
|---|---|---|
| `NEXT_MONTH_SETTLEMENT` | MEDIUM | Jan transaction settled in Feb — missing from month-end close, understates Jan revenue |
| `ROUNDING_DIFF` | LOW | Sub-$1 amount mismatch — internal ledger stores raw floats, bank rounds to 2 decimal places |
| `AGGREGATE_ROUNDING` | LOW/MEDIUM | Batch of transactions that individually match but diverge when summed — float accumulation |
| `DUPLICATE_SETTLEMENT` | HIGH | Same transaction settled more than once — merchant was paid double |
| `ORPHAN_REFUND` | HIGH/MEDIUM | Negative transaction with no settlement record — refund issued with no bank record |
| `UNSETTLED` | HIGH/MEDIUM | Transaction exists in ledger but bank has no settlement — payment may have silently failed |

---

## Project Structure

```
onelab/
├── app.py               # HTTP server + all API endpoints
├── dashboard.html       # Full frontend — tabs, charts, filters, export
├── reconcile.py         # Reconciliation engine — core gap detection logic
├── generate_data.py     # Synthetic test data generator (63 txns, 6 gap types)
├── test_reconcile.py    # 27 unit + integration tests
├── transactions.csv     # Generated internal ledger (auto-created)
├── settlements.csv      # Generated bank settlement file (auto-created)
├── Procfile             # Railway deployment start command
├── runtime.txt          # Python version pin (3.11.9)
├── requirements.txt     # No external dependencies — pure stdlib
└── .gitignore           # Excludes uploads and cache
```

---

## File-by-File Explanation

### `app.py` — HTTP Server
Pure Python stdlib HTTP server. No Flask, no Django, no external dependencies.

- Serves `dashboard.html` at `GET /`
- `GET /api/gaps` — runs the reconciliation engine and returns all gaps as JSON
- `GET /api/ledger` — returns every transaction joined with its settlement(s) as JSON
- `GET /api/stats` — returns total transaction count
- `POST /api/upload` — accepts two CSV files (transactions + settlements), runs reconciliation on them, returns gaps as JSON. Uses manual multipart boundary parsing (compatible with Python 3.13+ where the `cgi` module was removed)
- Reads `PORT` from environment variable so Railway can inject it
- Binds to `0.0.0.0` so it's reachable from outside the container
- Auto-runs `generate_data.py` on first request if CSV files don't exist

### `dashboard.html` — Frontend
Single-file frontend. No React, no build step, no npm. Pure HTML + CSS + vanilla JS.

**Reconciliation Gaps tab:**
- KPI summary cards (Total Gaps, High/Medium/Low risk, per-type counts) — clickable to filter
- Financial impact strip (Net Discrepancy, Over-Settled, Under-Settled, Unreconciled Value, Avg Settlement Lag)
- Day-by-day bar chart showing when gaps occurred, colour-coded by severity
- Plain-English explanation cards for each gap type found
- Filterable, sortable gap table with type badge, risk level, amounts, diff, settlement lag, and detail
- CSV export of current filtered view
- Upload zone — drag your own CSVs and reconcile against real data

**Full Ledger tab:**
- Summary KPIs (Matched, Mismatch, Unsettled, Orphan Refund, Duplicate counts + totals)
- Search by txn_id, ref_id, amount, or date
- Filter by status (Matched / Mismatch / Unsettled / Orphan Refund / Duplicate)
- Sortable table showing every transaction with its transaction date AND settlement date side by side
- CSV export of current filtered view

### `reconcile.py` — Reconciliation Engine
The core logic. Takes two CSV file paths, returns a list of gap dictionaries.

**How it works:**
1. Loads both CSVs into memory
2. Indexes settlements by `txn_id` into a dict
3. For each transaction:
   - No settlement found → `UNSETTLED` (or `ORPHAN_REFUND` if amount is negative)
   - More than one settlement found → `DUPLICATE_SETTLEMENT`
   - Settlement is in a different month → `NEXT_MONTH_SETTLEMENT`
   - Amount differs by less than $1.00 → `ROUNDING_DIFF`
4. After the per-row pass, groups transactions by settlement date and checks if the batch sum diverges even when individual diffs are tiny → `AGGREGATE_ROUNDING`
5. Attaches `severity` (HIGH / MEDIUM / LOW) to every gap based on dollar impact
6. Attaches `explanation` — plain-English description of what the gap means for the business
7. Attaches `lag_days` — days between transaction date and settlement date

**Severity rules:**
- `DUPLICATE_SETTLEMENT` → HIGH if over-settled by >$50, else MEDIUM
- `UNSETTLED` → HIGH if transaction >$100, else MEDIUM
- `ORPHAN_REFUND` → HIGH if refund >$50, else MEDIUM
- `NEXT_MONTH_SETTLEMENT` → always MEDIUM
- `AGGREGATE_ROUNDING` → LOW if batch diff <$0.05, else MEDIUM
- `ROUNDING_DIFF` → always LOW

### `generate_data.py` — Test Data Generator
Generates realistic synthetic data with deliberately planted gaps. Uses `random.seed(99)` so output is deterministic.

**What it generates:**
- 50 clean normal transactions (Jan 2024, settle 1–2 days later in Jan, amounts $5–$999)
- **GAP 1** — 2 next-month settlements: Jan 30 txn settles Feb 1, Jan 31 txn settles Feb 2
- **GAP 2** — 5 rounding batch txns: internal amount `10.333`, bank settles `10.33`. Per-row diff is $0.003 (invisible), but batch diff across 5 txns is $0.015 (only visible when summed)
- **GAP 3** — 2 duplicate settlements: same `txn_id` appears twice in the settlements file
- **GAP 4** — 2 orphan refunds: negative-amount transactions with no settlement record
- **GAP 5** — 2 unsettled transactions: positive transactions with no settlement at all

Total: 63 transactions, 61 settlements

### `test_reconcile.py` — Test Suite
27 unit and integration tests. All self-contained — no external files needed (uses `tempfile`).

**Test classes:**
- `TestNextMonthSettlement` — 4 tests: detected, not flagged same-month, Jan 31 edge case, detail contains dates
- `TestRoundingDiff` — 4 tests: detected, exact match clean, large diff not flagged as rounding, negative diff
- `TestAggregateRounding` — 4 tests: batch diverges flagged, exact batch clean, single txn not flagged, detail contains count
- `TestDuplicateSettlement` — 4 tests: two settlements flagged, single clean, diff calculation correct, three settlements
- `TestOrphanRefund` — 4 tests: negative no settlement flagged, positive unsettled not orphan, zero amount not orphan, multiple orphans
- `TestUnsettled` — 2 tests: no settlement flagged, settled not flagged
- `TestCleanData` — 1 test: zero gaps for perfect data
- `TestMultiGap` — 1 test: next-month + rounding on same transaction simultaneously
- `TestIntegration` — 3 tests: all 6 gap types present in generated CSVs, gap count reasonable, txn IDs non-empty

### `Procfile` — Railway Start Command
```
web: python app.py
```
Tells Railway how to start the application.

### `runtime.txt` — Python Version
```
python-3.11.9
```
Pins Python to 3.11 to avoid Railway defaulting to 3.13+ where the `cgi` module was removed.

### `requirements.txt`
Empty (comment only). No external dependencies — the entire project runs on Python stdlib. The file exists so Railway's Python buildpack detects the project correctly.

---

## Assumptions

| # | Assumption |
|---|---|
| 1 | Amounts are in USD |
| 2 | Internal ledger stores raw floats (can have 3+ decimal places) |
| 3 | Bank always rounds settlement amounts to exactly 2 decimal places |
| 4 | Refunds are negative-amount transactions in the ledger |
| 5 | Orphan refund = negative transaction with no settlement record |
| 6 | Report month = January 2024, cutoff = 2024-01-31 23:59:59 |
| 7 | Datetimes are naive UTC — no timezone conversion |
| 8 | Duplicate = same `txn_id` appears more than once in the settlements file |
| 9 | Aggregate rounding = batch where all per-row diffs < $0.01 but sum diff != 0 |
| 10 | No `customer_id` in dataset — orphan refund identified by negative amount + no settlement |

---

## Run Locally

```bash
# 1. Generate demo data
python generate_data.py

# 2. Start the server
python app.py
# Dashboard at http://localhost:5000

# 3. Run tests
python -m pytest test_reconcile.py -v
```

---

## Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Select this repo
4. Railway auto-detects Python, reads `Procfile`, injects `PORT` automatically
5. Click **Generate Domain**
6. Live in ~90 seconds

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Serves the dashboard HTML |
| GET | `/api/gaps` | Returns all reconciliation gaps as JSON |
| GET | `/api/ledger` | Returns all transactions joined with settlements as JSON |
| GET | `/api/stats` | Returns `{ txn_count: N }` |
| POST | `/api/upload` | Accepts `transactions` + `settlements` CSV files, returns gaps as JSON |

---

## What It Would Get Wrong in Production

**1. Timezone naivety** — The engine uses naive datetimes with no timezone conversion. A transaction at 11 PM EST on Jan 31 is 4 AM UTC on Feb 1. Depending on which clock the ledger and bank use, the same transaction could be classified as either January or February, causing false `NEXT_MONTH_SETTLEMENT` flags or missing real ones.

**2. Partial settlements misread as duplicates** — Banks routinely split one large transaction into multiple partial settlement batches (e.g. $500 settled as $300 + $200). This engine flags any `txn_id` with more than one settlement row as `DUPLICATE_SETTLEMENT`, generating false positives on any platform that uses partial fulfillment.

**3. FX gaps misclassified as rounding** — On a multi-currency platform, the difference between internal amount and settled amount often reflects FX conversion rates, not float truncation. The `ROUNDING_DIFF` threshold of "diff < $1.00" would silently swallow legitimate FX discrepancies on small transactions while flagging correct settlements on large ones where the FX spread exceeds $1.
