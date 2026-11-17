# Production Risks — What This Would Get Wrong

## The 3 Things This Gets Wrong in Production

**1. Timezone naivety will misclassify month-boundary transactions.**
This engine uses naive datetimes with no timezone conversion — a transaction recorded
at 11:00 PM EST on January 31st is 04:00 AM UTC on February 1st, so depending on
which clock the ledger and the bank use, the same transaction could be classified as
either a January transaction or a February one, causing false NEXT_MONTH_SETTLEMENT
flags or missing real ones entirely.

**2. Partial settlements will be misidentified as duplicates.**
Banks routinely split a single large transaction into multiple partial settlement
batches (e.g., a $500 transaction settled as $300 + $200 across two days); this
engine flags any txn_id with more than one settlement row as DUPLICATE_SETTLEMENT,
which would generate hundreds of false positives on any real payments platform that
uses batch settlement with partial fulfillment.

**3. Multi-currency rounding gaps will be misclassified as float noise.**
On a platform processing GBP, EUR, or any non-USD currency, the difference between
the internal amount and the settled amount often reflects FX conversion rates applied
at settlement time, not floating-point truncation — this engine's ROUNDING_DIFF
threshold of "diff < $1.00" would silently swallow legitimate FX discrepancies on
small transactions while flagging correct settlements on large ones where the FX
spread exceeds $1.

---

## Additional Production Gaps (bonus)

- **No idempotency check on re-runs** — running reconciliation twice on the same data
  produces duplicate gap records if results are persisted to a database.
- **No handling of chargebacks** — a chargeback reverses a settlement; this engine
  has no concept of settlement reversals and would leave the original transaction
  permanently flagged as DUPLICATE_SETTLEMENT.
- **Scale** — loading entire CSVs into memory works for thousands of rows; at millions
  of transactions (real payments volume) this needs streaming/chunked processing or
  a SQL-based approach.
