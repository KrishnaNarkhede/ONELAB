# Brainstorming Thread — OneLab AI Fitness Assessment

> Full unedited reasoning. Not cleaned up.

---

**Me:** Ok so the problem is: payments company, books don't balance at month end.
They have their own transaction ledger AND the bank settlement file.
The two should match. They don't. Find out why.

First thought — what are the actual ways these two datasets can diverge?

1. **Timing** — transactions are recorded instantly, settlements are batched 1-2 days later.
   So a Jan 30 transaction might settle Feb 1. At month-end close, Jan's books show the
   transaction but the bank file doesn't have it yet. Or vice versa — bank has it, ledger doesn't.

2. **Rounding** — internal systems often store floats with more precision than the bank.
   Bank always rounds to 2dp. If you have 10.333 internally and bank pays 10.33, that's
   a $0.003 gap per transaction. Individually invisible. But if you have 1000 of those
   transactions, that's $3 missing. Classic reconciliation trap.

3. **Duplicates** — either side can have duplicates. Bank retries a settlement. Internal
   system double-posts a transaction. Either way, one side has 2 rows for what should be 1.

4. **Refunds without originals** — a refund is processed but the original transaction
   it's refunding either doesn't exist in the dataset, was in a prior period, or was
   already removed. The refund is an orphan.

5. **Missing settlements entirely** — transaction exists, no settlement ever came.
   Could be a failed payment that wasn't caught, or a settlement that went to a different
   account/batch.

6. **Currency conversion** — not in scope here since we're USD only, but worth noting
   in production.

---

**Me:** Ok so what data do I need to generate?

Two CSV files:
- `transactions.csv` — the internal ledger. One row per payment event.
  Fields: txn_id, amount, created_at, note
- `settlements.csv` — the bank file. One row per settlement.
  Fields: ref_id, txn_id, amount, settled_at, note

The txn_id is the join key. Every transaction should have exactly one settlement
with the same txn_id, same amount, settled within 1-2 days.

Plant the gaps deliberately so I can verify detection.

---

**Me:** What assumptions am I making?

- Amounts in USD
- Internal ledger stores raw floats (can have 3+ decimal places)
- Bank always rounds to exactly 2 decimal places
- Refunds are negative-amount transactions in the ledger
- "Orphan refund" = negative txn with no settlement (bank never processed it)
  OR negative txn with no corresponding positive txn (refund for a sale we can't find)
  → I'll use the simpler definition: negative txn with no settlement record
- Month = January 2024, cutoff = Jan 31 23:59:59 UTC
- "Rounding only visible when summed" = batch of txns where each individual
  diff rounds away, but the sum of diffs is non-zero. Classic float accumulation.

---

**Me:** How should the reconciliation engine work?

Simple approach:
1. Load both CSVs
2. Index settlements by txn_id
3. For each transaction:
   - No settlement → UNSETTLED (or ORPHAN_REFUND if negative)
   - Multiple settlements → DUPLICATE_SETTLEMENT
   - Settlement in wrong month → NEXT_MONTH_SETTLEMENT
   - Amount mismatch < $1 → ROUNDING_DIFF
4. After per-row pass: group by settlement date, check if batch sums diverge
   even when individual diffs are tiny → AGGREGATE_ROUNDING

---

**Me:** What would this get wrong in production?

1. **Timezone handling** — I'm using naive datetimes. Production has UTC vs local time
   issues. A Jan 31 11pm EST transaction is Feb 1 4am UTC. Month-end cutoff depends
   entirely on which timezone you use. This engine would misclassify those.

2. **Currency** — I assumed USD only. Multi-currency platforms have FX conversion gaps
   that look like rounding but are actually exchange rate differences. This engine
   would flag them all as ROUNDING_DIFF incorrectly.

3. **Partial settlements** — banks sometimes split one transaction into multiple
   partial settlements (e.g., $100 settled as $60 + $40). This engine would flag
   that as DUPLICATE_SETTLEMENT when it's actually correct. Need amount-aware
   deduplication logic.

---

Me: What's the UI need to show?

- Summary cards: count per gap type
- Financial impact: total discrepancy in dollars
- Filterable table: click a gap type to see only those rows
- Each row: gap type badge, txn_id (truncated), amounts, diff, date, detail text
- No framework dependencies — pure stdlib so it runs anywhere

---

Me: Ok let's build it.
