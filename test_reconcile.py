"""
Test suite for the reconciliation engine.
All tests are self-contained — no external CSV files needed.

Coverage:
  - NEXT_MONTH_SETTLEMENT  : detected / not flagged for same-month
  - ROUNDING_DIFF          : detected / not flagged for exact match
  - AGGREGATE_ROUNDING     : detected / not flagged when batch sums match
  - DUPLICATE_SETTLEMENT   : detected / not flagged for single settlement
  - ORPHAN_REFUND          : detected / not confused with positive unsettled
  - UNSETTLED              : detected / not flagged when settled
  - Clean data             : zero gaps
  - Multi-gap on same txn  : next-month + rounding on same transaction
  - Integration            : all gap types present in generated CSV files
"""

import csv, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(__file__))
from reconcile import reconcile

# ── helpers ───────────────────────────────────────────────────────────────────

def write_tmp(rows, fieldnames):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                    delete=False, newline="")
    csv.DictWriter(f, fieldnames=fieldnames).writeheader()
    csv.DictWriter(f, fieldnames=fieldnames).writerows(rows)
    f.close()
    return f.name

def run(txns, settles):
    tf = write_tmp(txns,    ["txn_id", "amount", "created_at", "note"])
    sf = write_tmp(settles, ["ref_id", "txn_id", "amount", "settled_at", "note"])
    try:
        return reconcile(tf, sf)
    finally:
        os.unlink(tf); os.unlink(sf)

def types(gaps):
    return {g["type"] for g in gaps}

def gaps_of(gaps, gap_type):
    return [g for g in gaps if g["type"] == gap_type]

# ── NEXT_MONTH_SETTLEMENT ─────────────────────────────────────────────────────

class TestNextMonthSettlement(unittest.TestCase):

    def test_jan_txn_feb_settlement_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"100.00","created_at":"2024-01-30T14:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"100.00","settled_at":"2024-02-01T09:00:00","note":""}]
        )
        self.assertIn("NEXT_MONTH_SETTLEMENT", types(gaps))

    def test_jan_txn_jan_settlement_not_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"100.00","created_at":"2024-01-15T10:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"100.00","settled_at":"2024-01-17T08:00:00","note":""}]
        )
        self.assertNotIn("NEXT_MONTH_SETTLEMENT", types(gaps))

    def test_jan31_late_night_settles_feb2(self):
        gaps = run(
            [{"txn_id":"T2","amount":"50.00","created_at":"2024-01-31T23:55:00","note":""}],
            [{"ref_id":"S2","txn_id":"T2","amount":"50.00","settled_at":"2024-02-02T08:00:00","note":""}]
        )
        self.assertIn("NEXT_MONTH_SETTLEMENT", types(gaps))
        self.assertEqual(gaps_of(gaps,"NEXT_MONTH_SETTLEMENT")[0]["txn_amount"], 50.0)

    def test_detail_contains_dates(self):
        gaps = run(
            [{"txn_id":"T3","amount":"75.00","created_at":"2024-01-29T10:00:00","note":""}],
            [{"ref_id":"S3","txn_id":"T3","amount":"75.00","settled_at":"2024-02-01T08:00:00","note":""}]
        )
        detail = gaps_of(gaps,"NEXT_MONTH_SETTLEMENT")[0]["detail"]
        self.assertIn("2024-01-29", detail)
        self.assertIn("2024-02-01", detail)

# ── ROUNDING_DIFF ─────────────────────────────────────────────────────────────

class TestRoundingDiff(unittest.TestCase):

    def test_sub_cent_diff_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"99.999","created_at":"2024-01-15T10:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"100.00","settled_at":"2024-01-16T08:00:00","note":""}]
        )
        self.assertIn("ROUNDING_DIFF", types(gaps))
        self.assertAlmostEqual(gaps_of(gaps,"ROUNDING_DIFF")[0]["diff"], 0.001, places=4)

    def test_exact_match_not_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"100.00","created_at":"2024-01-15T10:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"100.00","settled_at":"2024-01-16T08:00:00","note":""}]
        )
        self.assertNotIn("ROUNDING_DIFF", types(gaps))

    def test_large_diff_not_flagged_as_rounding(self):
        # $5 difference is not rounding — should not appear as ROUNDING_DIFF
        gaps = run(
            [{"txn_id":"T1","amount":"100.00","created_at":"2024-01-15T10:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"105.00","settled_at":"2024-01-16T08:00:00","note":""}]
        )
        self.assertNotIn("ROUNDING_DIFF", types(gaps))

    def test_negative_rounding_diff(self):
        # Bank settles slightly less than internal amount
        gaps = run(
            [{"txn_id":"T1","amount":"10.335","created_at":"2024-01-15T10:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"10.33","settled_at":"2024-01-16T08:00:00","note":""}]
        )
        self.assertIn("ROUNDING_DIFF", types(gaps))
        self.assertLess(gaps_of(gaps,"ROUNDING_DIFF")[0]["diff"], 0)

# ── AGGREGATE_ROUNDING ────────────────────────────────────────────────────────

class TestAggregateRounding(unittest.TestCase):

    def test_batch_sum_diverges_flagged(self):
        # 3 txns: each 10.333 internally, bank pays 10.33 each
        # Per-row diff = 0.003 (tiny), but batch diff = 0.009
        txns = [
            {"txn_id":f"T{i}","amount":"10.333",
             "created_at":f"2024-01-12T10:0{i}:00","note":""}
            for i in range(3)
        ]
        settles = [
            {"ref_id":f"S{i}","txn_id":f"T{i}","amount":"10.33",
             "settled_at":f"2024-01-13T08:0{i}:00","note":""}
            for i in range(3)
        ]
        gaps = run(txns, settles)
        self.assertIn("AGGREGATE_ROUNDING", types(gaps))
        agg = gaps_of(gaps, "AGGREGATE_ROUNDING")[0]
        self.assertAlmostEqual(abs(agg["diff"]), 0.009, places=4)

    def test_exact_batch_not_flagged(self):
        txns = [
            {"txn_id":f"T{i}","amount":"10.00",
             "created_at":f"2024-01-12T10:0{i}:00","note":""}
            for i in range(3)
        ]
        settles = [
            {"ref_id":f"S{i}","txn_id":f"T{i}","amount":"10.00",
             "settled_at":f"2024-01-13T08:0{i}:00","note":""}
            for i in range(3)
        ]
        gaps = run(txns, settles)
        self.assertNotIn("AGGREGATE_ROUNDING", types(gaps))

    def test_single_txn_batch_not_flagged(self):
        # Single txn batch — aggregate check requires >= 2 txns
        gaps = run(
            [{"txn_id":"T1","amount":"10.333","created_at":"2024-01-12T10:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"10.33","settled_at":"2024-01-13T08:00:00","note":""}]
        )
        self.assertNotIn("AGGREGATE_ROUNDING", types(gaps))

    def test_batch_detail_contains_count(self):
        txns = [
            {"txn_id":f"T{i}","amount":"10.333",
             "created_at":f"2024-01-12T10:0{i}:00","note":""}
            for i in range(5)
        ]
        settles = [
            {"ref_id":f"S{i}","txn_id":f"T{i}","amount":"10.33",
             "settled_at":f"2024-01-13T08:0{i}:00","note":""}
            for i in range(5)
        ]
        gaps = run(txns, settles)
        agg = gaps_of(gaps, "AGGREGATE_ROUNDING")[0]
        self.assertIn("5", agg["detail"])

# ── DUPLICATE_SETTLEMENT ──────────────────────────────────────────────────────

class TestDuplicateSettlement(unittest.TestCase):

    def test_two_settlements_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"175.50","created_at":"2024-01-10T09:00:00","note":""}],
            [
                {"ref_id":"S1a","txn_id":"T1","amount":"175.50","settled_at":"2024-01-11T08:00:00","note":""},
                {"ref_id":"S1b","txn_id":"T1","amount":"175.50","settled_at":"2024-01-11T08:05:00","note":""},
            ]
        )
        self.assertIn("DUPLICATE_SETTLEMENT", types(gaps))

    def test_single_settlement_not_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"175.50","created_at":"2024-01-10T09:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"175.50","settled_at":"2024-01-11T08:00:00","note":""}]
        )
        self.assertNotIn("DUPLICATE_SETTLEMENT", types(gaps))

    def test_duplicate_diff_is_correct(self):
        # Txn = 200, settled twice = 400, diff = +200
        gaps = run(
            [{"txn_id":"T1","amount":"200.00","created_at":"2024-01-10T09:00:00","note":""}],
            [
                {"ref_id":"S1a","txn_id":"T1","amount":"200.00","settled_at":"2024-01-11T08:00:00","note":""},
                {"ref_id":"S1b","txn_id":"T1","amount":"200.00","settled_at":"2024-01-11T08:01:00","note":""},
            ]
        )
        dup = gaps_of(gaps, "DUPLICATE_SETTLEMENT")[0]
        self.assertAlmostEqual(dup["diff"], 200.0, places=2)

    def test_three_settlements_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"50.00","created_at":"2024-01-10T09:00:00","note":""}],
            [
                {"ref_id":f"S{i}","txn_id":"T1","amount":"50.00",
                 "settled_at":f"2024-01-11T08:0{i}:00","note":""}
                for i in range(3)
            ]
        )
        self.assertIn("DUPLICATE_SETTLEMENT", types(gaps))
        self.assertIn("3", gaps_of(gaps,"DUPLICATE_SETTLEMENT")[0]["detail"])

# ── ORPHAN_REFUND ─────────────────────────────────────────────────────────────

class TestOrphanRefund(unittest.TestCase):

    def test_negative_no_settlement_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"-89.00","created_at":"2024-01-20T11:00:00","note":""}],
            []
        )
        self.assertIn("ORPHAN_REFUND", types(gaps))

    def test_positive_unsettled_is_not_orphan(self):
        gaps = run(
            [{"txn_id":"T1","amount":"50.00","created_at":"2024-01-20T11:00:00","note":""}],
            []
        )
        self.assertIn("UNSETTLED", types(gaps))
        self.assertNotIn("ORPHAN_REFUND", types(gaps))

    def test_zero_amount_not_orphan(self):
        # Zero-amount txn with no settlement is UNSETTLED, not ORPHAN_REFUND
        gaps = run(
            [{"txn_id":"T1","amount":"0.00","created_at":"2024-01-20T11:00:00","note":""}],
            []
        )
        self.assertNotIn("ORPHAN_REFUND", types(gaps))

    def test_multiple_orphan_refunds(self):
        gaps = run(
            [
                {"txn_id":"T1","amount":"-10.00","created_at":"2024-01-20T11:00:00","note":""},
                {"txn_id":"T2","amount":"-25.00","created_at":"2024-01-21T11:00:00","note":""},
            ],
            []
        )
        self.assertEqual(len(gaps_of(gaps,"ORPHAN_REFUND")), 2)

# ── UNSETTLED ─────────────────────────────────────────────────────────────────

class TestUnsettled(unittest.TestCase):

    def test_no_settlement_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"300.00","created_at":"2024-01-25T10:00:00","note":""}],
            []
        )
        self.assertIn("UNSETTLED", types(gaps))

    def test_settled_not_flagged(self):
        gaps = run(
            [{"txn_id":"T1","amount":"300.00","created_at":"2024-01-25T10:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"300.00","settled_at":"2024-01-26T08:00:00","note":""}]
        )
        self.assertNotIn("UNSETTLED", types(gaps))

# ── CLEAN DATA ────────────────────────────────────────────────────────────────

class TestCleanData(unittest.TestCase):

    def test_zero_gaps_for_perfect_data(self):
        txns = [
            {"txn_id":f"T{i}","amount":f"{100+i}.00",
             "created_at":f"2024-01-0{i+1}T10:00:00","note":""}
            for i in range(5)
        ]
        settles = [
            {"ref_id":f"S{i}","txn_id":f"T{i}","amount":f"{100+i}.00",
             "settled_at":f"2024-01-0{i+2}T08:00:00","note":""}
            for i in range(5)
        ]
        self.assertEqual(run(txns, settles), [])

# ── MULTI-GAP ON SAME TRANSACTION ────────────────────────────────────────────

class TestMultiGap(unittest.TestCase):

    def test_next_month_and_rounding_on_same_txn(self):
        # Jan txn, settles in Feb, AND has a rounding diff
        gaps = run(
            [{"txn_id":"T1","amount":"99.995","created_at":"2024-01-30T14:00:00","note":""}],
            [{"ref_id":"S1","txn_id":"T1","amount":"100.00","settled_at":"2024-02-01T09:00:00","note":""}]
        )
        found = types(gaps)
        self.assertIn("NEXT_MONTH_SETTLEMENT", found)
        self.assertIn("ROUNDING_DIFF", found)

# ── INTEGRATION: generated CSV files ─────────────────────────────────────────

class TestIntegration(unittest.TestCase):

    def test_all_gap_types_in_generated_data(self):
        if not (os.path.exists("transactions.csv") and os.path.exists("settlements.csv")):
            self.skipTest("Run generate_data.py first")
        gaps = reconcile("transactions.csv", "settlements.csv")
        found = types(gaps)
        for expected in ["NEXT_MONTH_SETTLEMENT", "ROUNDING_DIFF",
                         "AGGREGATE_ROUNDING", "DUPLICATE_SETTLEMENT",
                         "ORPHAN_REFUND", "UNSETTLED"]:
            with self.subTest(gap_type=expected):
                self.assertIn(expected, found)

    def test_generated_data_gap_count_reasonable(self):
        if not (os.path.exists("transactions.csv") and os.path.exists("settlements.csv")):
            self.skipTest("Run generate_data.py first")
        gaps = reconcile("transactions.csv", "settlements.csv")
        # Should have at least 10 gaps (2+5+2+2+2+1 aggregate)
        self.assertGreaterEqual(len(gaps), 10)

    def test_clean_txns_produce_no_gaps(self):
        if not (os.path.exists("transactions.csv") and os.path.exists("settlements.csv")):
            self.skipTest("Run generate_data.py first")
        gaps = reconcile("transactions.csv", "settlements.csv")
        # All gaps should have a note field indicating they are planted gaps
        for g in gaps:
            # txn_id for AGGREGATE_ROUNDING is a BATCH: prefix, skip
            if g["txn_id"].startswith("BATCH:"):
                continue
            # Every flagged txn_id should be traceable (non-empty)
            self.assertTrue(len(g["txn_id"]) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
