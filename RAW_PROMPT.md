
## Raw Prompt (as fed to the AI coding tool)
A payments company's books don't balance at month end.
They have two datasets:
  1. transactions.csv — internal ledger, one row per payment (txn_id, amount, created_at)
  2. settlements.csv  — bank file, one row per settlement (ref_id, txn_id, amount, settled_at)

The txn_id is the join key. Every transaction should have exactly one matching settlement
with the same amount, settled within 1-2 days.

Do all of the following:

1. GENERATE both CSV files with realistic data (50+ normal rows).
   Plant exactly these gap types:
     a. A transaction that settled the following month (Jan txn, Feb settlement)
     b. A rounding difference that only shows when summed (batch of txns where
        internal float != bank 2dp, gap invisible per-row but visible in total)
     c. A duplicate entry in the settlements dataset (same txn_id settled twice)
     d. A refund (negative amount) with no matching settlement

2. BUILD a reconciliation engine in Python that detects all gap types:
     NEXT_MONTH_SETTLEMENT, ROUNDING_DIFF, AGGREGATE_ROUNDING,
     DUPLICATE_SETTLEMENT, ORPHAN_REFUND, UNSETTLED

3. BUILD a web dashboard (no external dependencies, pure stdlib) that shows:
     - Summary cards per gap type with counts
     - Financial impact (net discrepancy, over-settled, under-settled)
     - Filterable table of all gaps with: type badge, txn_id, amounts, diff, date, detail

4. WRITE test cases covering:
     - Each gap type detected correctly
     - Each gap type NOT falsely triggered on clean data
     - Edge cases: multi-gap on same txn, 3x duplicate, batch aggregate rounding
     - Integration test against the generated CSV files

State all assumptions. Use January 2024 as the report month.
