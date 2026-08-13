"""
Unit tests for Dynamic Multi-Model Router Agent (TASK-E8).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.agents.model_router import (
    ComplexityTier,
    ModelProviderChain,
    ModelRoutingTracker,
    QueryComplexityAnalyzer,
    analyze_query_complexity,
    get_routing_telemetry,
    route_and_execute,
)


class TestQueryComplexityAnalyzer(unittest.TestCase):
    def test_analyze_fast_tier(self):
        query = "How do I format a docstring in python?"
        score = QueryComplexityAnalyzer.analyze(query)
        self.assertEqual(score.tier, ComplexityTier.FAST)
        self.assertLess(score.score, 35)

    def test_analyze_balanced_tier(self):
        query = "Please check this function for bugs and explain why line 10 fails."
        score = QueryComplexityAnalyzer.analyze(query)
        self.assertEqual(score.tier, ComplexityTier.BALANCED)
        self.assertGreaterEqual(score.score, 35)
        self.assertLess(score.score, 70)

    def test_analyze_deep_reasoning_tier(self):
        query = (
            "Perform a deep architectural redesign to eliminate race condition bottlenecks, "
            "concurrency deadlocks, and memory leak vulnerabilities across multi-module graph traversal."
        )
        score = QueryComplexityAnalyzer.analyze(query)
        self.assertEqual(score.tier, ComplexityTier.DEEP_REASONING)
        self.assertGreaterEqual(score.score, 70)


@patch("src.agents.model_router.ModelProviderChain._call_ollama", return_value=None)
class TestModelProviderChain(unittest.TestCase):
    def test_routing_decision_deep_reasoning(self, mock_ollama):
        score = QueryComplexityAnalyzer.analyze("deep architectural redesign for race condition")
        decision = ModelProviderChain.get_routing_decision(score)

        self.assertIn("deepseek-r1", decision.primary_model)
        self.assertEqual(decision.primary_provider, "ollama")

    def test_fallback_execution_success(self, mock_ollama):
        score = QueryComplexityAnalyzer.analyze("format code")
        decision = ModelProviderChain.get_routing_decision(score)

        answer, prov, model, fallbacks = ModelProviderChain.execute_chain(
            decision, "format code"
        )
        self.assertIsNotNone(answer)
        self.assertIsNotNone(prov)
        self.assertIsNotNone(model)


@patch("src.agents.model_router.ModelProviderChain._call_ollama", return_value=None)
class TestRouterTelemetryAndPublicAPI(unittest.TestCase):
    def test_route_and_execute_fast(self, mock_ollama):
        res = route_and_execute("format docstring")
        self.assertEqual(res["complexity_tier"], "FAST")
        self.assertIn("telemetry", res)
        self.assertGreater(res["telemetry"]["total_queries"], 0)

    def test_route_and_execute_deep(self, mock_ollama):
        query = "deep architectural refactoring race condition memory leak"
        res = route_and_execute(query)
        self.assertEqual(res["complexity_tier"], "DEEP_REASONING")
        self.assertGreaterEqual(res["complexity_score"], 65)

    def test_analyze_query_complexity_api(self, mock_ollama):
        res = analyze_query_complexity("simple lookup")
        self.assertIn("complexity_tier", res)
        self.assertIn("complexity_score", res)


if __name__ == "__main__":
    unittest.main()

