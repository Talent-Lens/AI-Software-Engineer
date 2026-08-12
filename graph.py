"""
Full pipeline: Bug Detection Agent -> Review Agent -> Security Auditor Agent -> retry or final answer.
"""

from typing import TypedDict, Any, cast
from langgraph.graph import StateGraph, END

from src.agents.bug_detection import analyze_and_explain
from src.agents.review_agent import review_bug_detection_output
from src.agents.security_auditor import audit_file

MAX_ATTEMPTS = 3


class PipelineState(TypedDict):

    filepath: str
    agent_response: dict
    review: dict
    security_response: dict
    attempts: int


def detect_node(state: PipelineState) -> dict:
    attempt = state["attempts"] + 1
    print(f"[detect_node] attempt {attempt}: analyzing {state['filepath']}")
    result = analyze_and_explain(state["filepath"])
    return {"agent_response": result, "attempts": attempt}


def review_node(state: PipelineState) -> dict:
    print("[review_node] reviewing bug detection output")
    review = review_bug_detection_output(state["agent_response"], filepath=state.get("filepath"))
    print("[review_node] approved" if review["approved"] else f"[review_node] rejected: {review['issues']}")
    return {"review": review}


def security_node(state: PipelineState) -> dict:
    print(f"[security_node] running SAST security audit on {state['filepath']}")
    security_res = audit_file(state["filepath"])
    scorecard = security_res.get("details", {}).get("scorecard", {})
    status = scorecard.get("status", "PASS")
    score = scorecard.get("score", 100)
    print(f"[security_node] completed: Status={status}, Score={score}/100")
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
