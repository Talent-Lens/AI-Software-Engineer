"""
Unit tests for Human-in-the-Loop (HITL) Hard Negative Store (TASK-E9).
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.retrieval.hard_negative_store import (
    FeedbackType,
    HardNegativeStore,
    apply_hard_negative_penalties,
    get_hard_negative_stats,
    record_user_feedback,
)
from src.schema import Chunk, RetrievalResult


class TestHardNegativeStore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self.tmp_dir.name, "test_negatives.json")
        self.store = HardNegativeStore(storage_path=self.store_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_record_feedback_accept_and_reject(self):
        e1 = self.store.record_feedback("query 1", "c1", "file1.py", "def foo(): pass", "ACCEPT")
        e2 = self.store.record_feedback("query 2", "c2", "file2.py", "try: pass except: pass", "REJECT", "Bare except is bad")

        self.assertEqual(e1.feedback_type, FeedbackType.ACCEPT)
        self.assertEqual(e2.feedback_type, FeedbackType.REJECT)

        stats = self.store.get_stats()
        self.assertEqual(stats.total_events, 2)
        self.assertEqual(stats.accept_count, 1)
        self.assertEqual(stats.reject_count, 1)
        self.assertEqual(stats.rejection_rate, 0.5)
        self.assertIn("file2.py", stats.top_rejected_files)

    def test_similarity_computation(self):
        sim = self.store.compute_similarity("def calculate_total(): pass", "def calculate_total(): return 0")
        self.assertGreater(sim, 0.3)

        sim_diff = self.store.compute_similarity("alpha beta gamma", "foo bar baz")
        self.assertEqual(sim_diff, 0.0)

    def test_apply_hard_negative_penalties(self):
        # 1. Record a rejected chunk in store
        query = "fix bare except in connection pool"
        bad_code = "try:\n    connect()\nexcept:\n    pass\n"
        self.store.record_feedback(query, "c_bad", "src/db/connection.py", bad_code, "REJECT")

        # 2. Create candidate set containing bad_code and a clean_code
        c_bad = Chunk(
            id="c_bad",
            file_path="src/db/connection.py",
            start_line=10,
            end_line=15,
            type="function",
            name="connect",
            code=bad_code,
        )
        c_clean = Chunk(
            id="c_clean",
            file_path="src/db/connection.py",
            start_line=20,
            end_line=25,
            type="function",
            name="safe_connect",
            code="def safe_connect(): try: connect() except Exception as e: log(e)",
        )

        # candidates in initial order [c_bad, c_clean]
        res = apply_hard_negative_penalties(query, [c_bad, c_clean], store=self.store)

        def _get_cid(item):
            ch = item["chunk"]
            return ch.id if isinstance(ch, Chunk) else ch.get("id")

        bad_res = [r for r in res if _get_cid(r) == "c_bad"][0]
        self.assertTrue(bad_res["hard_negative_penalty_applied"])
        self.assertGreater(bad_res["penalty_deduction"], 0.0)


    def test_public_api(self):
        res = record_user_feedback("test query", "c1", "REJECT", "User rejected", store=self.store)
        self.assertEqual(res["status"], "SUCCESS")

        stats = get_hard_negative_stats(store=self.store)
        self.assertGreater(stats["total_events"], 0)


if __name__ == "__main__":
    unittest.main()
