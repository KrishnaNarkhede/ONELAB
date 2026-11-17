"""
Reconciliation engine — detects 5 gap types:

  NEXT_MONTH_SETTLEMENT  Jan transaction settled in Feb+
  ROUNDING_DIFF          Per-row amount mismatch < $1 (float/truncation noise)
  AGGREGATE_ROUNDING     Batch of txns individually match to 2dp but sum diverges
  DUPLICATE_SETTLEMENT   Same txn_id appears more than once in settlements
  ORPHAN_REFUND          Negative transaction with no settlement
  UNSETTLED              Transaction has no settlement at all

Assumptions:
  - Report month is January 2024
  - Rounding threshold: per-row diff < $1.00 is a rounding issue, not a dispute
  - Aggregate rounding: group txns by settlement date; compare sum(txn) vs sum(settled)
    if individual diffs are all < $0.01 but batch diff > $0.00 -> AGGREGATE_ROUNDING
  - Orphan refund: negative txn with no settlement (no bank record of the refund)
"""

import csv
from datetime import datetime
from collections import defaultdict

REPORT_MONTH = (2024, 1)

SEVERITY_RULES = {
    "DUPLICATE_SETTLEMENT": lambda g: "HIGH"   if abs(g["diff"] or 0) > 50  else "MEDIUM",
    "UNSETTLED":            lambda g: "HIGH"   if abs(g["txn_amount"] or 0) > 100 else "MEDIUM",
    "ORPHAN_REFUND":        lambda g: "HIGH"   if abs(g["txn_amount"] or 0) > 50  else "MEDIUM",
    "NEXT_MONTH_SETTLEMENT":lambda g: "MEDIUM",
    "AGGREGATE_ROUNDING":   lambda g: "LOW"    if abs(g["diff"] or 0) < 0.05 else "MEDIUM",
    "ROUNDING_DIFF":        lambda g: "LOW",
}

GAP_EXPLANATIONS = {
    "NEXT_MONTH_SETTLEMENT": "Transaction recorded in Jan but bank settled in Feb. It counts in Feb revenue, not Jan. Your Jan books are understated by this amount.",
    "ROUNDING_DIFF":         "Internal ledger stores more decimal places than the bank uses. The per-transaction gap is tiny but accumulates across thousands of transactions.",
    "AGGREGATE_ROUNDING":    "Individually each transaction looks fine, but the batch total diverges. The bank applied rounding to the sum, not each row. You are short by the batch diff.",
    "DUPLICATE_SETTLEMENT":  "The same transaction was settled twice. You paid the merchant double. You are owed a refund of the over-settled amount.",
    "ORPHAN_REFUND":         "A refund was issued with no matching original transaction in the ledger. Either the original is missing from the dataset or this refund was issued in error.",
    "UNSETTLED":             "Transaction exists in the ledger but the bank has no record of settling it. Money may be stuck in processing or the payment silently failed.",
}


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def parse_dt(s):
    return datetime.fromisoformat(s)


def reconcile(txn_file="transactions.csv", settle_file="settlements.csv"):
    txns    = load_csv(txn_file)
    settles = load_csv(settle_file)

    settle_map = defaultdict(list)
    for s in settles:
        settle_map[s["txn_id"]].append(s)

    gaps = []

    # Track per-settlement-date batches for aggregate rounding check
    # key: settle_date (YYYY-MM-DD), value: list of (txn_amt, settle_amt)
    batch_pairs = defaultdict(list)

    for t in txns:
        txn_id  = t["txn_id"]
        txn_amt = float(t["amount"])
        txn_dt  = parse_dt(t["created_at"])
        matched = settle_map.get(txn_id, [])

        # ── UNSETTLED / ORPHAN_REFUND ────────────────────────────────────────
        if not matched:
            gap_type = "ORPHAN_REFUND" if txn_amt < 0 else "UNSETTLED"
            detail   = ("Negative (refund) transaction with no settlement and no matching original"
                        if txn_amt < 0 else
                        "Transaction has no corresponding settlement")
            gaps.append({
                "type": gap_type,
                "txn_id": txn_id,
                "txn_amount": txn_amt,
                "txn_date": t["created_at"],
                "settle_date": None,
                "settle_amount": None,
                "diff": None,
                "detail": detail
            })
            continue

        # ── DUPLICATE_SETTLEMENT ─────────────────────────────────────────────
        if len(matched) > 1:
            total_settled = sum(float(s["amount"]) for s in matched)
            gaps.append({
                "type": "DUPLICATE_SETTLEMENT",
                "txn_id": txn_id,
                "txn_amount": txn_amt,
                "txn_date": t["created_at"],
                "settle_date": matched[0]["settled_at"],
                "settle_amount": total_settled,
                "diff": round(total_settled - txn_amt, 4),
                "detail": (f"{len(matched)} settlements found; "
                           f"total settled={total_settled:.2f} vs txn={txn_amt:.2f} "
                           f"(over-settled by ${total_settled - txn_amt:.2f})")
            })

        for s in matched:
            settle_amt = float(s["amount"])
            settle_dt  = parse_dt(s["settled_at"])
            settle_date_key = settle_dt.strftime("%Y-%m-%d")

            # ── NEXT_MONTH_SETTLEMENT ────────────────────────────────────────
            if ((settle_dt.year, settle_dt.month) != REPORT_MONTH and
                    (txn_dt.year, txn_dt.month) == REPORT_MONTH):
                gaps.append({
                    "type": "NEXT_MONTH_SETTLEMENT",
                    "txn_id": txn_id,
                    "txn_amount": txn_amt,
                    "txn_date": t["created_at"],
                    "settle_date": s["settled_at"],
                    "settle_amount": settle_amt,
                    "diff": 0,
                    "detail": (f"Txn recorded {t['created_at'][:10]} (Jan) "
                               f"but settled {s['settled_at'][:10]} "
                               f"— missing from Jan close, appears in Feb")
                })

            # ── ROUNDING_DIFF (per-row) ──────────────────────────────────────
            diff = round(settle_amt - txn_amt, 6)
            if diff != 0 and abs(diff) < 1.0:
                gaps.append({
                    "type": "ROUNDING_DIFF",
                    "txn_id": txn_id,
                    "txn_amount": txn_amt,
                    "txn_date": t["created_at"],
                    "settle_date": s["settled_at"],
                    "settle_amount": settle_amt,
                    "diff": round(diff, 6),
                    "detail": (f"txn={txn_amt:.4f}  settled={settle_amt:.4f}  "
                               f"diff={diff:+.4f}  (sub-$1 rounding gap)")
                })

            # Collect for aggregate rounding check (only same-month settlements)
            if (settle_dt.year, settle_dt.month) == REPORT_MONTH:
                batch_pairs[settle_date_key].append((txn_amt, settle_amt))

    # ── AGGREGATE_ROUNDING ───────────────────────────────────────────────────
    # For each settlement date: if every individual diff < $0.01 but the
    # batch sum diverges, flag it — this is the "only visible when summed" case
    for date_key, pairs in batch_pairs.items():
        if len(pairs) < 2:
            continue
        per_row_diffs = [abs(round(s - t, 6)) for t, s in pairs]
        batch_txn_sum    = round(sum(t for t, _ in pairs), 6)
        batch_settle_sum = round(sum(s for _, s in pairs), 6)
        batch_diff       = round(batch_settle_sum - batch_txn_sum, 6)

        # Only flag if: all per-row diffs are tiny AND batch diff is non-zero
        if all(d < 0.01 for d in per_row_diffs) and batch_diff != 0:
            gaps.append({
                "type": "AGGREGATE_ROUNDING",
                "txn_id": f"BATCH:{date_key}",
                "txn_amount": batch_txn_sum,
                "txn_date": date_key,
                "settle_date": date_key,
                "settle_amount": batch_settle_sum,
                "diff": round(batch_diff, 6),
                "detail": (f"Settlement date {date_key}: "
                           f"{len(pairs)} txns sum to {batch_txn_sum:.4f} internally "
                           f"but bank settled {batch_settle_sum:.4f} "
                           f"(batch diff={batch_diff:+.4f})")
            })

    # Attach severity + explanation to every gap
    for g in gaps:
        rule = SEVERITY_RULES.get(g["type"])
        g["severity"]    = rule(g) if rule else "LOW"
        g["explanation"] = GAP_EXPLANATIONS.get(g["type"], "")

    # Settlement lag: days between txn created_at and settled_at
    settle_map2 = defaultdict(list)
    for s in load_csv(settle_file):
        settle_map2[s["txn_id"]].append(s)
    for g in gaps:
        if g.get("settle_date") and g.get("txn_date") and not g["txn_id"].startswith("BATCH:"):
            try:
                lag = (parse_dt(g["settle_date"]) - parse_dt(g["txn_date"])).days
                g["lag_days"] = lag
            except Exception:
                g["lag_days"] = None
        else:
            g["lag_days"] = None

    return gaps


def summary(gaps):
    from collections import Counter
    counts = Counter(g["type"] for g in gaps)
    print("\n=== RECONCILIATION SUMMARY ===")
    for gap_type, count in sorted(counts.items()):
        print(f"  {gap_type:<30} {count}")
    print(f"  {'TOTAL':<30} {len(gaps)}")
    print()
    for g in gaps:
        print(f"[{g['type']}]")
        print(f"  txn_id : {g.get('txn_id','')[:20]}")
        print(f"  detail : {g.get('detail','')}")
        print()


if __name__ == "__main__":
    gaps = reconcile()
    summary(gaps)
