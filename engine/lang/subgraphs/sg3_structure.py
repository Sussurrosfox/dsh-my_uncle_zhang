# -*- coding: utf-8 -*-
"""
lang.subgraphs.sg3_structure
----------------------------
SG3 结构重建子图 (to_lang.md §5.3)
流程:
  START -> structure_rebuilder -> gate_dependency
                 ▲                      │ fail
                 └──────────────────────┘
"""

from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from lang.state import GraphState
from lang.node_factory import make_agent_node, make_gate_node, load_agents_registry
from lang.gates.registry import get_gate


def build_sg3_subgraph(registry: dict = None, max_retry: int = 3):
    """构建 SG3 结构重建子图"""
    if not registry:
        registry = load_agents_registry()

    g = StateGraph(GraphState)
    dep_gate = get_gate("dependency_gate")

    # 注册节点
    g.add_node("structure_rebuilder", make_agent_node("structure_rebuilder", registry))
    g.add_node("gate_dependency", make_gate_node(dep_gate))

    # 边与拓扑
    g.add_edge(START, "structure_rebuilder")
    g.add_edge("structure_rebuilder", "gate_dependency")

    def route_dependency_gate(state: GraphState) -> str:
        latest = state.gate_results[-1] if state.gate_results else None
        if not latest or latest.passed:
            return END
        retries = state.retry_counts.get("structure_rebuilder", 0)
        if retries >= max_retry or state.stop_flag:
            return END
        return "structure_rebuilder"

    g.add_conditional_edges(
        "gate_dependency",
        route_dependency_gate,
        {
            "structure_rebuilder": "structure_rebuilder",
            END: END
        }
    )

    return g
