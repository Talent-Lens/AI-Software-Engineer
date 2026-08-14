"""
Full pipeline: Bug Detection Agent -> Review Agent -> Security Auditor Agent -> retry or final answer.
Instrumented with OpenTelemetry & Agent Tracing (TASK-FS5).
"""

from typing import TypedDict, Any, cast
from langgraph.graph import StateGraph, END

from src.agents.bug_detection import analyze_and_explain
from src.agents.review_agent import review_bug_detection_output
from src.agents.security_auditor import audit_file
from src.telemetry.tracer import trace_span

MAX_ATTEMPTS = 3


class PipelineState(TypedDict):
    filepath: str
    agent_response: dict
    review: dict
    security_response: dict
    attempts: int


def detect_node(state: PipelineState) -> dict:
    attempt = state["attempts"] + 1
    with trace_span("agent_node:bug_detection", attributes={"filepath": state["filepath"], "attempt": attempt}) as span:
        print(f"[detect_node] attempt {attempt}: analyzing {state['filepath']}")
        result = analyze_and_explain(state["filepath"])
        # Estimate / track token metrics for bug detection agent
        prompt_len = len(state.get("filepath", "")) * 4
        comp_len = len(str(result)) // 3
        span.record_tokens(prompt_tokens=max(prompt_len, 100), completion_tokens=max(comp_len, 50), model="qwen2.5-coder:7b")
        return {"agent_response": result, "attempts": attempt}


def review_node(state: PipelineState) -> dict:
    with trace_span("agent_node:code_reviewer", attributes={"filepath": state.get("filepath")}) as span:
        print("[review_node] reviewing bug detection output")
        review = review_bug_detection_output(state["agent_response"], filepath=state.get("filepath"))
        print("[review_node] approved" if review["approved"] else f"[review_node] rejected: {review['issues']}")
        span.record_tokens(prompt_tokens=150, completion_tokens=80, model="qwen2.5-coder:7b")
        return {"review": review}


def security_node(state: PipelineState) -> dict:
    with trace_span("agent_node:security_auditor", attributes={"filepath": state["filepath"]}) as span:
        print(f"[security_node] running SAST security audit on {state['filepath']}")
        security_res = audit_file(state["filepath"])
        scorecard = security_res.get("details", {}).get("scorecard", {})
        status = scorecard.get("status", "PASS")
        score = scorecard.get("score", 100)
        print(f"[security_node] completed: Status={status}, Score={score}/100")
        span.record_tokens(prompt_tokens=200, completion_tokens=120, model="qwen2.5-coder:7b")
        return {"security_response": security_res}


def route_after_review(state: PipelineState) -> str:
    if state["review"]["approved"]:
        return "security"
    elif state["attempts"] >= MAX_ATTEMPTS:
        print("[router] max attempts reached, proceeding to security check best effort")
        return "security"
    else:
        return "retry"


graph = StateGraph(cast(Any, PipelineState))
graph.add_node("detect", detect_node)
graph.add_node("review", review_node)
graph.add_node("security", security_node)

graph.set_entry_point("detect")
graph.add_edge("detect", "review")

graph.add_conditional_edges(
    "review",
    route_after_review,
    {"retry": "detect", "security": "security"}
)
graph.add_edge("security", END)

app = graph.compile()


import os


def run_pipeline(filepath: str) -> dict:
    with trace_span("langgraph_pipeline:run_pipeline", attributes={"filepath": filepath}):
        return app.invoke({
            "filepath": filepath,
            "agent_response": {},
            "review": {},
            "security_response": {},
            "attempts": 0,
        })


if __name__ == "__main__":
    sample_path = __file__
    final = run_pipeline(sample_path)
    print("-" * 60)
    print("FINAL SUMMARY:")
    print(final.get("agent_response", {}).get("summary", "No summary"))
    print("-" * 60)
    print("REVIEW:", final.get("review", {}))
    print("-" * 60)
    print("SECURITY SCORECARD:")
    sec_details = final.get("security_response", {}).get("details", {})
    print(sec_details.get("markdown_scorecard", "No security scorecard"))