# -*- coding: utf-8 -*-
"""
lang.subgraphs.sg1_source
-------------------------
SG1 来源核验子图 (to_lang.md §5.1)
流程:
  START -> evidence_builder -> source_verifier -> gate_source
                                  ▲                  │ fail
                                  └── evidence_fixer ◄┘
"""

from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from lang.state import GraphState
from lang.node_factory import make_agent_node, make_gate_node, load_agents_registry
from lang.gates.registry import get_gate


def build_sg1_subgraph(registry: dict = None, max_retry: int = 3):
    """构建 SG1 来源核验子图"""
    if not registry:
        registry = load_agents_registry()

    g = StateGraph(GraphState)
    source_gate = get_gate("source_gate")

    # 注册节点
    g.add_node("evidence_builder", make_agent_node("evidence_builder", registry))
    g.add_node("source_verifier", make_agent_node("source_verifier", registry))
    g.add_node("evidence_fixer", make_agent_node("evidence_fixer", registry))
    g.add_node("gate_source", make_gate_node(source_gate))

    # 边与拓扑
    g.add_edge(START, "evidence_builder")
    g.add_edge("evidence_builder", "source_verifier")
    g.add_edge("source_verifier", "gate_source")
    g.add_edge("evidence_fixer", "source_verifier")

    def route_source_gate(state: GraphState) -> str:
        latest = state.gate_results[-1] if state.gate_results else None
        if not latest or latest.passed:
            return END
        # 熔断检测
        retries = state.retry_counts.get("evidence_fixer", 0)
        if retries >= max_retry or state.stop_flag:
            return END
        return "evidence_fixer"

    g.add_conditional_edges(
        "gate_source",
        route_source_gate,
        {
            "evidence_fixer": "evidence_fixer",
            END: END
        }
    )

    return g
