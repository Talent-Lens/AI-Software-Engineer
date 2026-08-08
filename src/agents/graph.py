from langgraph.graph import StateGraph, END
from typing import TypedDict
from agents.code_chat import code_chat
from agents.documentation_agent import generate_docs


class GraphState(TypedDict):
    mode: str        # "chat" or "docs"
    question: str
    file_path: str
    result: dict


def code_chat_node(state: GraphState) -> GraphState:
    response = code_chat(state["question"])
    state["result"] = response.model_dump()
    return state


def docs_node(state: GraphState) -> GraphState:
    response = generate_docs(state["file_path"])
    state["result"] = response.model_dump()
    return state


def route(state: GraphState) -> str:
    return "chat" if state["mode"] == "chat" else "docs"


graph = StateGraph(GraphState)
graph.add_node("chat", code_chat_node)
graph.add_node("docs", docs_node)
graph.set_conditional_entry_point(route)
graph.add_edge("chat", END)
graph.add_edge("docs", END)

app = graph.compile()