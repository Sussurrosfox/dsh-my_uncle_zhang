# -*- coding: utf-8 -*-
"""
lang.subgraphs.sg2_diagnosis
----------------------------
SG2 防自学诊断子图 (to_lang.md §5.2)
流程:
  START -> reading_auditor -> diagnosis_aggregator -> gate_diagnosis
                 ▲                                         │ fail
                 └─────────────────────────────────────────┘
"""

from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from lang.state import GraphState
from lang.node_factory import make_agent_node, make_gate_node, load_agents_registry
from lang.gates.registry import get_gate


def diagnosis_aggregator_node(state: GraphState) -> dict:
    """聚合与精炼诊断记录，消除重复"""
    # 基础透传，保留经 reducer 合并后的 diagnoses 视图
    return {"diagnoses": state.diagnoses}


def build_sg2_subgraph(registry: dict = None, max_retry: int = 3):
    """构建 SG2 防自学诊断子图"""
    if not registry:
        registry = load_agents_registry()

    g = StateGraph(GraphState)
    diag_gate = get_gate("diagnosis_gate")

    # 注册节点
    g.add_node("reading_auditor", make_agent_node("reading_auditor", registry))
    g.add_node("diagnosis_aggregator", diagnosis_aggregator_node)
    g.add_node("gate_diagnosis", make_gate_node(diag_gate))

    # 边与拓扑
    g.add_edge(START, "reading_auditor")
    g.add_edge("reading_auditor", "diagnosis_aggregator")
    g.add_edge("diagnosis_aggregator", "gate_diagnosis")

    def route_diagnosis_gate(state: GraphState) -> str:
        latest = state.gate_results[-1] if state.gate_results else None
        if not latest or latest.passed:
            return END
        retries = state.retry_counts.get("reading_auditor", 0)
        if retries >= max_retry or state.stop_flag:
            return END
        return "reading_auditor"

    g.add_conditional_edges(
        "gate_diagnosis",
        route_diagnosis_gate,
        {
            "reading_auditor": "reading_auditor",
            END: END
        }
    )

    return g
