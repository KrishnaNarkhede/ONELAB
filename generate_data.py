"""
Generate synthetic payments reconciliation test data.

Assumptions:
- Transactions are recorded in UTC at time of customer payment
- Settlements arrive 1-2 business days later from the bank
- Amounts are in USD; internal ledger stores raw floats, bank rounds to 2dp
- Transaction IDs are UUIDs; settlement references map back via txn_id
- Refunds are negative-amount transactions recorded as separate txn rows
- Month-end cutoff is 2024-01-31 23:59:59 UTC
- A "rounding difference only visible when summed" means: each individual
  settlement matches its txn to 2dp, but the bank applies a single floor()
  to the batch total — creating a 1-cent gap only visible at the aggregate
- Duplicate = same txn_id appears twice in the settlements file
- Orphan refund = negative txn with no corresponding positive txn_id in ledger
"""

import csv, uuid, random
from datetime import datetime, timedelta

random.seed(99)

TRANSACTIONS_FILE = "transactions.csv"
SETTLEMENTS_FILE  = "settlements.csv"

transactions = []
settlements  = []

def txn(txn_id, amount, created_at, note=""):
    return {"txn_id": txn_id, "amount": amount, "created_at": created_at, "note": note}

def settle(ref_id, txn_id, amount, settled_at, note=""):
    return {"ref_id": ref_id, "txn_id": txn_id, "amount": amount,
            "settled_at": settled_at, "note": note}

# ── 50 clean normal transactions (Jan, settle 1-2 days later in Jan) ─────────
for _ in range(50):
    tid    = str(uuid.uuid4())
    amt    = round(random.uniform(5, 999), 2)
    day    = random.randint(1, 27)
    hour   = random.randint(0, 23)
    minute = random.randint(0, 59)
    created  = datetime(2024, 1, day, hour, minute)
    settled  = created + timedelta(days=random.randint(1, 2))
    transactions.append(txn(tid, amt, created.isoformat()))
    settlements.append(settle(str(uuid.uuid4()), tid, amt, settled.isoformat()))

# ── GAP 1: Next-month settlement ──────────────────────────────────────────────
# Jan 30 transaction, bank settles Feb 1 (crosses month boundary)
g1 = str(uuid.uuid4())
transactions.append(txn(g1, 312.50,
    datetime(2024, 1, 30, 14, 22).isoformat(), "GAP1_next_month"))
settlements.append(settle(str(uuid.uuid4()), g1, 312.50,
    datetime(2024, 2, 1, 9, 0).isoformat(), "GAP1_next_month"))

# Second next-month case: Jan 31 late night, settles Feb 2
g1b = str(uuid.uuid4())
transactions.append(txn(g1b, 88.00,
    datetime(2024, 1, 31, 23, 45).isoformat(), "GAP1b_next_month"))
settlements.append(settle(str(uuid.uuid4()), g1b, 88.00,
    datetime(2024, 2, 2, 8, 0).isoformat(), "GAP1b_next_month"))

# ── GAP 2: Rounding difference visible only when summed ───────────────────────
# 5 transactions each with a sub-cent internal amount.
# Individually each rounds to the same 2dp value — gap only appears in the SUM.
# e.g. 10.333 + 10.333 + 10.333 = 30.999 internally, but bank pays 3 x 10.33 = 30.99
# The per-row diff is 0.003 each — small enough to be "invisible" individually
# but the aggregate diff is $0.015 across the batch.
rounding_ids = []
for i in range(5):
    rid = str(uuid.uuid4())
    rounding_ids.append(rid)
    internal_amt = 10.333          # 3-decimal internal amount
    bank_amt     = round(internal_amt, 2)   # 10.33 — bank truncates
    transactions.append(txn(rid, internal_amt,
        datetime(2024, 1, 12, 10, i).isoformat(), f"GAP2_rounding_batch_{i}"))
    settlements.append(settle(str(uuid.uuid4()), rid, bank_amt,
        datetime(2024, 1, 13, 8, i).isoformat(), f"GAP2_rounding_batch_{i}"))

# ── GAP 3: Duplicate settlement entry ────────────────────────────────────────
g3 = str(uuid.uuid4())
transactions.append(txn(g3, 475.00,
    datetime(2024, 1, 8, 9, 0).isoformat(), "GAP3_duplicate"))
settlements.append(settle(str(uuid.uuid4()), g3, 475.00,
    datetime(2024, 1, 9, 8, 0).isoformat(), "GAP3_duplicate_original"))
settlements.append(settle(str(uuid.uuid4()), g3, 475.00,
    datetime(2024, 1, 9, 8, 3).isoformat(), "GAP3_duplicate_copy"))

# Second duplicate: different amount on the copy (partial duplicate)
g3b = str(uuid.uuid4())
transactions.append(txn(g3b, 200.00,
    datetime(2024, 1, 14, 11, 0).isoformat(), "GAP3b_partial_duplicate"))
settlements.append(settle(str(uuid.uuid4()), g3b, 200.00,
    datetime(2024, 1, 15, 8, 0).isoformat(), "GAP3b_partial_dup_original"))
settlements.append(settle(str(uuid.uuid4()), g3b, 200.00,
    datetime(2024, 1, 15, 8, 1).isoformat(), "GAP3b_partial_dup_copy"))

# ── GAP 4: Orphan refund (no matching original transaction) ───────────────────
g4 = str(uuid.uuid4())
transactions.append(txn(g4, -149.99,
    datetime(2024, 1, 18, 15, 30).isoformat(), "GAP4_orphan_refund"))
# No settlement — refund has no original txn in the ledger

# Second orphan refund
g4b = str(uuid.uuid4())
transactions.append(txn(g4b, -55.00,
    datetime(2024, 1, 22, 10, 0).isoformat(), "GAP4b_orphan_refund"))
# No settlement

# ── GAP 5: Unsettled transaction (transaction exists, no settlement at all) ───
g5 = str(uuid.uuid4())
transactions.append(txn(g5, 620.00,
    datetime(2024, 1, 25, 16, 0).isoformat(), "GAP5_unsettled"))
# No settlement row added

g5b = str(uuid.uuid4())
transactions.append(txn(g5b, 33.75,
    datetime(2024, 1, 26, 9, 0).isoformat(), "GAP5b_unsettled"))
# No settlement row added

# ── Write CSVs ────────────────────────────────────────────────────────────────
def write_csv(filename, rows, fieldnames):
    with open(filename, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

write_csv(TRANSACTIONS_FILE, transactions,
          ["txn_id", "amount", "created_at", "note"])
write_csv(SETTLEMENTS_FILE, settlements,
          ["ref_id", "txn_id", "amount", "settled_at", "note"])

print(f"Generated {len(transactions)} transactions -> {TRANSACTIONS_FILE}")
print(f"Generated {len(settlements)} settlements  -> {SETTLEMENTS_FILE}")
print()
print("Planted gaps:")
print("  GAP1  - 2x next-month settlement (Jan 30 + Jan 31 txns settle in Feb)")
print("  GAP2  - 5x rounding diff batch (10.333 internal vs 10.33 bank, gap only in sum)")
print("  GAP3  - 2x duplicate settlement (same txn_id settled twice)")
print("  GAP4  - 2x orphan refund (negative txn, no original, no settlement)")
print("  GAP5  - 2x unsettled transaction (txn exists, no settlement at all)")
