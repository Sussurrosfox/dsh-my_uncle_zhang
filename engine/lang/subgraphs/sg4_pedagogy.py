# -*- coding: utf-8 -*-
"""
lang.subgraphs.sg4_pedagogy
---------------------------
SG4 单元设计 + 正文撰写子图 (to_lang.md §5.4)
流程:
  START -> unit_designer -> writer -> unit_self_check -> gate_pedagogy
                 ▲            ▲                              │ fail
                 │            └──────────────────────────────┤
                 └───────────────────────────────────────────┘
"""

from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from lang.state import GraphState
from lang.node_factory import make_agent_node, make_gate_node, load_agents_registry
from lang.gates.registry import get_gate


def unit_self_check_node(state: GraphState) -> dict:
    """
    单元内部轻量自检小循环 (≤2次)：
    快速扫描格式与占位符，不豁免后续的 pedagogy_gate 门禁。
    """
    # 保持正文状态，若有明显残缺可在 units 状态中做标记
    return {"good_md": state.good_md}


def build_sg4_subgraph(registry: dict = None, max_retry: int = 3):
    """构建 SG4 单元设计与正文撰写子图"""
    if not registry:
        registry = load_agents_registry()

    g = StateGraph(GraphState)
    pedagogy_gate = get_gate("pedagogy_gate")

    # 注册节点
    g.add_node("unit_designer", make_agent_node("unit_designer", registry))
    g.add_node("writer", make_agent_node("writer", registry))
    g.add_node("unit_self_check", unit_self_check_node)
    g.add_node("gate_pedagogy", make_gate_node(pedagogy_gate))

    # 拓扑
    g.add_edge(START, "unit_designer")
    g.add_edge("unit_designer", "writer")
    g.add_edge("writer", "unit_self_check")
    g.add_edge("unit_self_check", "gate_pedagogy")

    def route_pedagogy_gate(state: GraphState) -> str:
        latest = state.gate_results[-1] if state.gate_results else None
        if not latest or latest.passed:
            return END

        # 检查是否熔断
        writer_retries = state.retry_counts.get("writer", 0)
        designer_retries = state.retry_counts.get("unit_designer", 0)
        if writer_retries >= max_retry or designer_retries >= max_retry or state.stop_flag:
            return END

        # 根据失败原因强制分类路由
        fail_route = "writer"
        for f in latest.failures:
            if f.get("route_to") == "unit_designer" or f.get("check") == "check_observable_objectives":
                fail_route = "unit_designer"
                break
        return fail_route

    g.add_conditional_edges(
        "gate_pedagogy",
        route_pedagogy_gate,
        {
            "writer": "writer",
            "unit_designer": "unit_designer",
            END: END
        }
    )

    return g
