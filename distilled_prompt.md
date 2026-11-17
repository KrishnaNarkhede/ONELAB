
## Distilled Prompt (the core of what matters)

Given two CSVs — an internal transaction ledger and a bank settlement file,
joined on txn_id — find every row where the two datasets disagree.

Disagreement types to detect:
  1. Settlement crossed the month boundary (timing gap)
  2. Amount differs by < $1 per row but accumulates in batch sum (rounding gap)
  3. Same txn_id appears twice in settlements (duplicate gap)
  4. Negative transaction with no settlement (orphan refund gap)
  5. Transaction with no settlement at all (missing settlement gap)

Output: structured list of gaps with type, amounts, diff, and human-readable detail.
```

---

## Key Assumptions Stated

| # | Assumption |
|---|-----------|
| 1 | Amounts in USD; internal ledger stores raw floats (3+ dp), bank rounds to 2dp |
| 2 | Refunds = negative-amount transactions; orphan = no settlement record |
| 3 | Report month = January 2024; cutoff = 2024-01-31 23:59:59 |
| 4 | Datetimes are naive UTC (no timezone conversion) |
| 5 | Duplicate = same txn_id in settlements file more than once |
| 6 | Aggregate rounding = batch where all per-row diffs < $0.01 but sum diff != 0 |
| 7 | No customer_id in dataset — orphan refund identified by negative amount + no settlement |
