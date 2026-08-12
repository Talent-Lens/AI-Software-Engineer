"""
Unit tests for Synthetic Multi-Language Bug Generator Agent (TASK-E7).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from src.eval.synthetic_bug_generator import (
    BugMutators,
    SyntheticDatasetGenerator,
    generate_synthetic_benchmark_dataset,
    inject_synthetic_bug,
)


class TestBugMutators(unittest.TestCase):
    def test_inject_bare_except(self):
        clean = "try:\n    x = 1\nexcept ValueError:\n    pass\n"
        res = BugMutators.inject_bare_except(clean)
        self.assertIsNotNone(res)
        buggy_code, bug_line, exp, fix = res
        self.assertIn("except:", buggy_code)
        self.assertEqual(bug_line, 3)

    def test_inject_sqli(self):
        clean = "cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))"
        res = BugMutators.inject_sqli(clean)
        self.assertIsNotNone(res)
        buggy_code, bug_line, exp, fix = res
        self.assertIn("f\"SELECT", buggy_code)

    def test_inject_hardcoded_secret(self):
        clean = "key = os.getenv('API_KEY')"
        res = BugMutators.inject_hardcoded_secret(clean)
        self.assertIsNotNone(res)
        buggy_code, bug_line, exp, fix = res
        self.assertIn("AKIAIOSFODNN7EXAMPLE", buggy_code)

    def test_inject_command_injection(self):
        clean = "subprocess.run(['ls', '-la'])"
        res = BugMutators.inject_command_injection(clean)
        self.assertIsNotNone(res)
        buggy_code, bug_line, exp, fix = res
        self.assertIn("os.system", buggy_code)

    def test_inject_unsafe_deserialization(self):
        clean = "data = json.loads(payload)"
        res = BugMutators.inject_unsafe_deserialization(clean)
        self.assertIsNotNone(res)
        buggy_code, bug_line, exp, fix = res
        self.assertIn("pickle.loads", buggy_code)

    def test_inject_off_by_one(self):
        clean = "for i in range(len(items)):\n    pass"
        res = BugMutators.inject_off_by_one(clean)
        self.assertIsNotNone(res)
        buggy_code, bug_line, exp, fix = res
        self.assertIn("range(len(items) + 1)", buggy_code)


class TestSyntheticDatasetGenerator(unittest.TestCase):
    def test_generate_100_pairs(self):
        generator = SyntheticDatasetGenerator()
        pairs = generator.generate_pairs(target_count=100)
        self.assertEqual(len(pairs), 100)

        # Check structure of generated pairs
        for p in pairs[:5]:
            self.assertTrue(p.id.startswith("BUG-BENCH-"))
            self.assertTrue(len(p.clean_code) > 0)
            self.assertTrue(len(p.buggy_code) > 0)
            self.assertGreater(p.bug_line, 0)
            self.assertTrue(len(p.explanation) > 0)

    def test_export_json_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_p = os.path.join(tmpdir, "synthetic_dataset.json")
            res_path = generate_synthetic_benchmark_dataset(target_count=100, output_path=out_p)

            self.assertTrue(os.path.exists(res_path))
            with open(res_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(len(data), 100)
            self.assertIn("bug_category", data[0])
            self.assertIn("golden_fix", data[0])


if __name__ == "__main__":
    unittest.main()
