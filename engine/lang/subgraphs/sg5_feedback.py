# -*- coding: utf-8 -*-
"""
lang.subgraphs.sg5_feedback
---------------------------
SG5 任务与反馈嵌入子图 (to_lang.md §5.5)
流程:
  START -> task_author -> gate_feedback
                ▲             │ fail
                └─────────────┘
"""

from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from lang.state import GraphState
from lang.node_factory import make_agent_node, make_gate_node, load_agents_registry
from lang.gates.registry import get_gate


def build_sg5_subgraph(registry: dict = None, max_retry: int = 3):
    """构建 SG5 任务嵌入子图"""
    if not registry:
        registry = load_agents_registry()

    g = StateGraph(GraphState)
    fb_gate = get_gate("feedback_gate")

    # 注册节点
    g.add_node("task_author", make_agent_node("task_author", registry))
    g.add_node("gate_feedback", make_gate_node(fb_gate))

    # 边
    g.add_edge(START, "task_author")
    g.add_edge("task_author", "gate_feedback")

    def route_feedback_gate(state: GraphState) -> str:
        latest = state.gate_results[-1] if state.gate_results else None
        if not latest or latest.passed:
            return END
        retries = state.retry_counts.get("task_author", 0)
        if retries >= max_retry or state.stop_flag:
            return END
        return "task_author"

    g.add_conditional_edges(
        "gate_feedback",
        route_feedback_gate,
        {
            "task_author": "task_author",
            END: END
        }
    )

    return g
