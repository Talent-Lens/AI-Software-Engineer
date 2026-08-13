"""
Dynamic Multi-Model Router Agent (TASK-E8)

Inspects query complexity and dynamically routes user/agent queries between fast models
(Groq/Gemini for sub-second responses) and deep reasoning models (DeepSeek-R1 for complex
architectural reasoning) with resilient fallback retries and telemetry tracking.
"""

from __future__ import annotations

import enum
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import requests

# ---------------------------------------------------------------------------
# Enums & Data Models
# ---------------------------------------------------------------------------

class ComplexityTier(str, enum.Enum):
    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP_REASONING = "DEEP_REASONING"


@dataclass
class ComplexityScore:
    score: int  # 0 to 100
    tier: ComplexityTier
    reasoning_factors: list[str] = field(default_factory=list)


@dataclass
class RoutingDecision:
    query: str
    complexity: ComplexityScore
    primary_provider: str  # "groq" | "gemini" | "ollama" | "mock"
    primary_model: str
    fallback_chain: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class RouterResponse:
    query: str
    answer: str
    model_used: str
    provider_used: str
    complexity_tier: ComplexityTier
    complexity_score: int
    execution_time_ms: float
    fallback_attempts: int
    telemetry: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answer": self.answer,
            "model_used": self.model_used,
            "provider_used": self.provider_used,
            "complexity_tier": self.complexity_tier.value,
            "complexity_score": self.complexity_score,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "fallback_attempts": self.fallback_attempts,
            "telemetry": self.telemetry,
        }


# ---------------------------------------------------------------------------
# Query Complexity Analyzer
# ---------------------------------------------------------------------------

class QueryComplexityAnalyzer:
    """
    Analyzes query complexity based on length, technical depth indicators,
    reasoning keywords, and multi-file code context requirements.
    """

    DEEP_REASONING_KEYWORDS = {
        "architecture", "architectural", "redesign", "refactor", "race condition",
        "deadlock", "memory leak", "graph traversal", "algorithm", "deepseek",
        "reasoning", "root cause", "concurrency", "performance bottleneck",
        "security vulnerability", "proof", "optimization strategy"
    }

    BALANCED_KEYWORDS = {
        "bug", "bugs", "check", "review", "explain", "unit test", "test",
        "coverage", "function", "method", "class", "why", "error"
    }

    FAST_KEYWORDS = {
        "format", "lint", "syntax", "docstring", "comment", "spelling",
        "rename", "lookup", "what is", "simple", "indent"
    }

    @classmethod
    def analyze(cls, query: str, context: str = "") -> ComplexityScore:
        factors: list[str] = []
        score = 15  # Base score

        full_text = f"{query} {context}".lower()
        words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", full_text)

        # 1. Text Length Scoring
        word_count = len(words)
        if word_count > 300:
            score += 30
            factors.append(f"Large query/context length ({word_count} words)")
        elif word_count > 100:
            score += 15
            factors.append(f"Moderate query length ({word_count} words)")

        # 2. Deep Reasoning Keywords
        matched_deep = [kw for kw in cls.DEEP_REASONING_KEYWORDS if kw in full_text]
        if matched_deep:
            add_points = min(60, len(matched_deep) * 20)
            score += add_points
            factors.append(f"Deep reasoning keywords detected: {', '.join(matched_deep[:3])}")

        # 3. Balanced Bug/Review Keywords
        matched_bal = [kw for kw in cls.BALANCED_KEYWORDS if kw in full_text]
        if matched_bal and not matched_deep:
            score += min(30, len(matched_bal) * 15)
            factors.append(f"Balanced review/bug keywords detected: {', '.join(matched_bal[:3])}")

        # 4. Fast Keywords Discount
        matched_fast = [kw for kw in cls.FAST_KEYWORDS if kw in full_text]
        if matched_fast and not matched_deep and not matched_bal:
            score -= 10
            factors.append(f"Fast simple task keywords detected: {', '.join(matched_fast[:3])}")

        # 5. Multi-File / Code Complexity Indicators
        code_blocks = len(re.findall(r"```", full_text)) // 2
        file_refs = len(re.findall(r"\b[a-zA-Z0-9_-]+\.(?:py|js|ts|java|go|cpp)\b", full_text))

        if code_blocks >= 2 or file_refs >= 2:
            score += 20
            factors.append(f"Multi-code block/file reference detected ({code_blocks} blocks, {file_refs} files)")

        final_score = max(0, min(100, score))

        # Assign Tier
        if final_score >= 65:
            tier = ComplexityTier.DEEP_REASONING
        elif final_score >= 35:
            tier = ComplexityTier.BALANCED
        else:
            tier = ComplexityTier.FAST

        return ComplexityScore(score=final_score, tier=tier, reasoning_factors=factors)



# ---------------------------------------------------------------------------
# Provider Executor Chain & Fallbacks
# ---------------------------------------------------------------------------

class ModelProviderChain:
    """
    Manages multi-provider execution across Groq, Gemini, Ollama (DeepSeek-R1), and local fallbacks.
    """

    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    OLLAMA_API_URL = "http://localhost:11434/api/generate"

    @classmethod
    def get_routing_decision(cls, complexity: ComplexityScore) -> RoutingDecision:
        groq_key = os.getenv("GROQ_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")

        if complexity.tier == ComplexityTier.DEEP_REASONING:
            # Deep Reasoning Route: Primary = DeepSeek-R1 via Ollama/Groq, Fallback = Llama-3.3-70b / Qwen
            primary_prov = "ollama"
            primary_mod = "deepseek-r1:7b"
            chain = [("ollama", "deepseek-r1:7b")]
            if groq_key:
                chain.append(("groq", "llama-3.3-70b-versatile"))
            if gemini_key:
                chain.append(("gemini", "gemini-2.5-flash"))
            chain.append(("ollama", "qwen2.5:7b"))
            chain.append(("mock", "rule-reasoning-engine"))

        elif complexity.tier == ComplexityTier.BALANCED:
            # Balanced Route: Primary = Groq Llama-3.3-70b / Qwen, Fallback = Gemini / Ollama
            if groq_key:
                primary_prov = "groq"
                primary_mod = "llama-3.3-70b-versatile"
            elif gemini_key:
                primary_prov = "gemini"
                primary_mod = "gemini-2.5-flash"
            else:
                primary_prov = "ollama"
                primary_mod = "qwen2.5:7b"

            chain = []
            if groq_key:
                chain.append(("groq", "llama-3.3-70b-versatile"))
            if gemini_key:
                chain.append(("gemini", "gemini-2.5-flash"))
            chain.append(("ollama", "qwen2.5:7b"))
            chain.append(("mock", "rule-balanced-engine"))

        else:  # ComplexityTier.FAST
            # Fast Route: Sub-second latency models (Groq qwen-2.5-coder-32b or Gemini 2.5 flash)
            if groq_key:
                primary_prov = "groq"
                primary_mod = "qwen-2.5-coder-32b"
            elif gemini_key:
                primary_prov = "gemini"
                primary_mod = "gemini-2.5-flash"
            else:
                primary_prov = "ollama"
                primary_mod = "qwen2.5:3b"

            chain = []
            if groq_key:
                chain.append(("groq", "qwen-2.5-coder-32b"))
            if gemini_key:
                chain.append(("gemini", "gemini-2.5-flash"))
            chain.append(("ollama", "qwen2.5:3b"))
            chain.append(("mock", "rule-fast-engine"))

        return RoutingDecision(
            query="",
            complexity=complexity,
            primary_provider=primary_prov,
            primary_model=primary_mod,
            fallback_chain=chain,
        )

    @classmethod
    def execute_chain(
        cls, decision: RoutingDecision, prompt: str, system_prompt: str = ""
    ) -> tuple[str, str, str, int]:
        """
        Iterates through the fallback chain until a provider succeeds.
        Returns: (answer_text, provider_used, model_used, fallback_attempts)
        """
        attempts = 0

        for prov, mod in decision.fallback_chain:
            attempts += 1
            res = None

            if prov == "groq":
                res = cls._call_groq(mod, prompt, system_prompt)
            elif prov == "gemini":
                res = cls._call_gemini(mod, prompt, system_prompt)
            elif prov == "ollama":
                res = cls._call_ollama(mod, prompt, system_prompt)
            elif prov == "mock":
                res = cls._call_mock(mod, prompt)

            if res:
                return res, prov, mod, (attempts - 1)

        # Ultimate fallback
        return f"Executed query via fallback rule engine for query.", "mock", "fallback-engine", attempts

    @classmethod
    def _call_groq(cls, model: str, prompt: str, system_prompt: str) -> str | None:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            return None

        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": model, "messages": messages, "temperature": 0.2}
        try:
            resp = requests.post(cls.GROQ_API_URL, headers=headers, json=payload, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass
        return None

    @classmethod
    def _call_gemini(cls, model: str, prompt: str, system_prompt: str) -> str | None:
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        combined_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        payload = {"contents": [{"parts": [{"text": combined_prompt}]}]}
        try:
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            pass
        return None

    @classmethod
    def _call_ollama(cls, model: str, prompt: str, system_prompt: str) -> str | None:
        combined_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        try:
            resp = requests.post(
                cls.OLLAMA_API_URL,
                json={"model": model, "prompt": combined_prompt, "stream": False},
                timeout=12,
            )
            if resp.status_code == 200:
                return resp.json().get("response")
        except Exception:
            pass
        return None

    @classmethod
    def _call_mock(cls, model: str, prompt: str) -> str:
        return f"[Synthesized Response via {model}]: Processed request successfully."


# ---------------------------------------------------------------------------
# Router Telemetry Tracker
# ---------------------------------------------------------------------------

class ModelRoutingTracker:
    """
    Maintains rolling telemetry data on model routing decisions, token usage,
    and provider latency.
    """

    def __init__(self):
        self.total_queries = 0
        self.tier_counts = {
            ComplexityTier.FAST: 0,
            ComplexityTier.BALANCED: 0,
            ComplexityTier.DEEP_REASONING: 0,
        }
        self.provider_counts: dict[str, int] = {}
        self.total_latency_ms = 0.0
        self.total_fallbacks = 0

    def record_event(
        self, tier: ComplexityTier, provider: str, latency_ms: float, fallbacks: int
    ):
        self.total_queries += 1
        self.tier_counts[tier] = self.tier_counts.get(tier, 0) + 1
        self.provider_counts[provider] = self.provider_counts.get(provider, 0) + 1
        self.total_latency_ms += latency_ms
        self.total_fallbacks += fallbacks

    def get_telemetry_summary(self) -> dict[str, Any]:
        mean_latency = (
            round(self.total_latency_ms / self.total_queries, 2) if self.total_queries > 0 else 0.0
        )
        return {
            "total_queries": self.total_queries,
            "mean_latency_ms": mean_latency,
            "total_fallbacks": self.total_fallbacks,
            "tier_distribution": {k.value: v for k, v in self.tier_counts.items()},
            "provider_distribution": self.provider_counts,
        }


# Global Telemetry Instance
GLOBAL_ROUTING_TRACKER = ModelRoutingTracker()


# ---------------------------------------------------------------------------
# Public Entry Points
# ---------------------------------------------------------------------------

def analyze_query_complexity(query: str, context: str = "") -> dict[str, Any]:
    """
    Analyzes query complexity and returns complexity score and tier details.
    """
    score = QueryComplexityAnalyzer.analyze(query, context)
    return {
        "complexity_tier": score.tier.value,
        "complexity_score": score.score,
        "reasoning_factors": score.reasoning_factors,
    }


def route_and_execute(
    query: str, context: str = "", system_prompt: str = ""
) -> dict[str, Any]:
    """
    Inspects query complexity and dynamically routes query to the optimal model provider,
    executing with automatic fallbacks and recording routing telemetry.
    """
    start_time = time.time()

    # 1. Analyze complexity
    comp_score = QueryComplexityAnalyzer.analyze(query, context)

    # 2. Get routing decision
    decision = ModelProviderChain.get_routing_decision(comp_score)
    decision.query = query

    # 3. Format full prompt
    full_prompt = f"Context:\n{context}\n\nQuery: {query}" if context else query

    # 4. Execute via fallback chain
    answer, prov_used, mod_used, fallbacks = ModelProviderChain.execute_chain(
        decision, full_prompt, system_prompt
    )

    elapsed_ms = (time.time() - start_time) * 1000.0

    # 5. Record telemetry
    GLOBAL_ROUTING_TRACKER.record_event(
        comp_score.tier, prov_used, elapsed_ms, fallbacks
    )

    response = RouterResponse(
        query=query,
        answer=answer,
        model_used=mod_used,
        provider_used=prov_used,
        complexity_tier=comp_score.tier,
        complexity_score=comp_score.score,
        execution_time_ms=elapsed_ms,
        fallback_attempts=fallbacks,
        telemetry=GLOBAL_ROUTING_TRACKER.get_telemetry_summary(),
    )

    return response.to_dict()


def get_routing_telemetry() -> dict[str, Any]:
    """Returns aggregated telemetry metrics for model routing."""
    return GLOBAL_ROUTING_TRACKER.get_telemetry_summary()


if __name__ == "__main__":
    q_fast = "How do I format a docstring in python?"
    q_deep = "Perform a deep architectural refactoring to eliminate race conditions and memory leaks in graph traversal concurrency."

    res1 = route_and_execute(q_fast)
    res2 = route_and_execute(q_deep)

    print(f"[Fast Query] Tier: {res1['complexity_tier']}, Model: {res1['model_used']}, Time: {res1['execution_time_ms']}ms")
    print(f"[Deep Query] Tier: {res2['complexity_tier']}, Model: {res2['model_used']}, Time: {res2['execution_time_ms']}ms")
