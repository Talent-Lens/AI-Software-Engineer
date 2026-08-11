"""
Full pipeline: Bug Detection Agent -> Review Agent -> retry or final answer.
"""

from typing import TypedDict, Any, cast
from langgraph.graph import StateGraph, END

from src.agents.bug_detection import analyze_and_explain
from src.agents.review_agent import review_bug_detection_output

MAX_ATTEMPTS = 3


class PipelineState(TypedDict):

    filepath: str
    agent_response: dict
    review: dict
    attempts: int


def detect_node(state: PipelineState) -> dict:
    attempt = state["attempts"] + 1
    print(f"[detect_node] attempt {attempt}: analyzing {state['filepath']}")
    result = analyze_and_explain(state["filepath"])
    return {"agent_response": result, "attempts": attempt}


def review_node(state: PipelineState) -> dict:
    print("[review_node] reviewing bug detection output")
    review = review_bug_detection_output(state["agent_response"])
    print("[review_node] approved" if review["approved"] else f"[review_node] rejected: {review['issues']}")
    return {"review": review}


def route_after_review(state: PipelineState) -> str:
    if state["review"]["approved"]:
        return "done"
    elif state["attempts"] >= MAX_ATTEMPTS:
        print("[router] max attempts reached, returning best effort")
        return "done"
    else:
        return "retry"


graph = StateGraph(cast(Any, PipelineState))
graph.add_node("detect", detect_node)
graph.add_node("review", review_node)

graph.set_entry_point("detect")
graph.add_edge("detect", "review")

graph.add_conditional_edges(
    "review",
    route_after_review,
    {"retry": "detect", "done": END}
)

app = graph.compile()


import os


def run_pipeline(filepath: str) -> dict:
    return app.invoke({
        "filepath": filepath,
        "agent_response": {},
        "review": {},
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